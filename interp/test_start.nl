/* SHA-256 implemented entirely in newlang using bitwise operators. */
/* No std helpers — all logic is pure newlang with arrays. */

/* ---------------------------------------------------------------------------
 * Static round constants K[0..63] — initialized once, read-only.
 * Each value fits in a signed 64-bit integer for the interpreter.
 * --------------------------------------------------------------------------- */

const K = [
    1116352408, 1899447441, 3049323471, 3921009573,
     961987163, 1508970993, 2453635748, 2870763221,
    3624381080,  310598401,  607225278, 1426881987,
    1925078388, 2162078206, 2614888103, 3248222580,
    3835390401, 4022224774,  264347078,  604807628,
     770255983, 1249150122, 1555081692, 1996064986,
    2554220882, 2821834349, 2952996808, 3210313671,
    3336571891, 3584528711, 113926993,  338241895,
     666307205,  773529912, 1294757372, 1396182291,
    1695183700, 1986661051, 2177026350, 2456956037,
    2730485921, 2820302411, 3259730800, 3345764771,
    3516065817, 3600352804, 4094571909,  275423344,
     430227734,  506948616,  659060556,  883997877,
     958139571, 1322822218, 1537002063, 1747873779,
    1955562222, 2024104815, 2227730452, 2361852424,
    2428436474, 2756734187, 3204031479, 3329325298,
];

/* ---------------------------------------------------------------------------
 * Helper: compute data_size mod 64.
 * --------------------------------------------------------------------------- */

fn data_rem_64(data_size) -> int {
    var rem = data_size;
    while (rem >= 64) { rem ← rem - 64; }
    return rem;
}

/* ---------------------------------------------------------------------------
 * SHA-256 padding helpers.
 *
 * The data object (Bytes) returns 0 for out-of-range reads, but SHA-256
 * padding requires a 0x80 byte after the message and a big-endian 64-bit
 * bit-length suffix.  These helpers overlay the padding on reads.
 * --------------------------------------------------------------------------- */

fn get_padded_byte(data, pos, data_size, total_size) -> int {
    if (pos < data_size) { return data.getbyte(pos); }
    if (pos == data_size) { return 128; }
    var len_start = total_size - 8;
    if (pos >= len_start) {
        var bit_len = data_size * 8;
        var byte_idx = pos - len_start;
        return (bit_len » ((7 - byte_idx) * 8)) & 255;
    }
    return 0;
}

fn get_padded_word(data, off, data_size, total_size) -> int {
    if (off + 4 <= data_size) { return data.getword(off); }
    var b0 = get_padded_byte(data, off, data_size, total_size);
    var b1 = get_padded_byte(data, off + 1, data_size, total_size);
    var b2 = get_padded_byte(data, off + 2, data_size, total_size);
    var b3 = get_padded_byte(data, off + 3, data_size, total_size);
    return ((b0 « 24) | (b1 « 16) | (b2 « 8) | b3) & 4294967295;
}

/* ---------------------------------------------------------------------------
 * SHA-256 sigma helpers for message-schedule expansion.
 * --------------------------------------------------------------------------- */

fn expand_s0(prev) -> int {
    /* σ₀(x) = ROTR(7,x) ⊕ ROTR(18,x) ⊕ SHR(3,x). */
    return ((prev ↻ 7) ^ (prev ↻ 18) ^ (prev » 3)) & 4294967295;
}

fn expand_s1(prev) -> int {
    /* σ₁(x) = ROTR(17,x) ⊕ ROTR(19,x) ⊕ SHR(10,x). */
    return ((prev ↻ 17) ^ (prev ↻ 19) ^ (prev » 10)) & 4294967295;
}

/* ---------------------------------------------------------------------------
 * sha256(data) — full SHA-256 implementation in pure newlang.
 *
 * Uses « » for shifts, ↺ ↻ for rotations, and subscript access for the
 * message schedule W[0..63] and round constants K[t].
 * --------------------------------------------------------------------------- */

fn sha256(data) -> int {
    var W = new i32[64];

    var data_size = data.size;

    /* Compute padded message length per SHA-256 spec. */
    var rem = data_rem_64(data_size);
    var pad_len = 55 - rem;
    if (pad_len < 0) { pad_len ← pad_len + 64; }
    var total_size = data_size + 1 + pad_len + 8;

    /* Initial hash values per FIPS 180-4 Section 5.3.3. */
    var H = [
        1779033703, 3144134277, 1013904242, 2773480762,
        1359893119, 2600822924, 528734635,  1541459225,
    ];

    /* Process each 64-byte block. */
    var blk_off = 0;
    while (blk_off < total_size) {
        /* --- Load W[0..15] from the current block (with padding overlay). --- */
        var i = 0;
        while (i < 16) {
            W[i] ← get_padded_word(data, blk_off + (i * 4), data_size, total_size);
            i ← i + 1;
        }

        /* --- Message-schedule expansion: W[16..63]. --- */
        var j = 16;
        while (j < 64) {
            W[j] ← (W[j - 16] + expand_s0(W[j - 15]) +
                     W[j - 7] + expand_s1(W[j - 2])) & 4294967295;
            j ← j + 1;
        }

        /* --- Initialize working variables v[0..7] from H[0..7]. --- */
        var v = new i32[8];
        var k = 0;
        while (k < 8) {
            v[k] ← H[k];
            k ← k + 1;
        }

        /* --- 64 compression rounds using K[t] and W[t]. --- */
        var t = 0;
        while (t < 64) {
            /* Σ₁(e) = ROTR(6,e) ⊕ ROTR(11,e) ⊕ ROTR(25,e). */
            var s1 = ((v[4] ↻ 6) ^ (v[4] ↻ 11) ^ (v[4] ↻ 25)) & 4294967295;

            /* ch(e,f,g) = (e ∧ f) ⊕ (¬e ∧ g). */
            var ch = (v[4] & v[5]) ^ (~v[4] & v[6]);

            /* t1 = h + Σ₁ + ch + K[t] + W[t]. */
            var t1 = (v[7] + s1 + ch + K[t] + W[t]) & 4294967295;

            /* Σ₀(a) = ROTR(2,a) ⊕ ROTR(13,a) ⊕ ROTR(22,a). */
            var s0 = ((v[0] ↻ 2) ^ (v[0] ↻ 13) ^ (v[0] ↻ 22)) & 4294967295;

            /* maj(a,b,c) = (a ∧ b) ⊕ (a ∧ c) ⊕ (b ∧ c). */
            var maj = (v[0] & v[1]) ^ (v[0] & v[2]) ^ (v[1] & v[2]);

            /* t2 = Σ₀ + maj. */
            var t2 = (s0 + maj) & 4294967295;

            /* Shift working variables right by one position. */
            v[1…7] ← v[0…6];
            v[0] ← (t1 + t2) & 4294967295;
            v[4] ← (v[4] + t1) & 4294967295;

            t ← t + 1;
        }

        /* --- Add compressed chunk to current hash state. --- */
        H ← (H + v) & 4294967295;

        blk_off ← blk_off + 64;
    }

    /* Pack final hash: H[0]«224 | … | H[7]. */
    var hash = 0;
    var k = 0;
    while (k < 8) {
        hash ← hash | (H[k] « ((7 - k) * 32));
        k ← k + 1;
    }
    return hash;
}

@start
fn main() -> none {
    var dir = std.fs.cwd();
    var file = dir.openFile("CLAUDE.md");
    var data = file.read_file(std.heap.allocator());
    var hash = sha256(data);
    std.print(hash);
}
