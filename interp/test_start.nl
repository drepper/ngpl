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
        return (bit_len >> ((7 - byte_idx) * 8)) & 255;
    }
    return 0;
}

fn get_padded_word(data, off, data_size, total_size) -> int {
    if (off + 4 <= data_size) { return data.getword(off); }
    var b0 = get_padded_byte(data, off, data_size, total_size);
    var b1 = get_padded_byte(data, off + 1, data_size, total_size);
    var b2 = get_padded_byte(data, off + 2, data_size, total_size);
    var b3 = get_padded_byte(data, off + 3, data_size, total_size);
    return ((b0 << 24) | (b1 << 16) | (b2 << 8) | b3) & 4294967295;
}

/* ---------------------------------------------------------------------------
 * SHA-256 sigma helpers for message-schedule expansion.
 * --------------------------------------------------------------------------- */

fn expand_s0(prev) -> int {
    /* ROTR(7,x) ^ ROTR(18,x) ^ SHR(3,x). */
    var r0_a = ((prev >> 7) | (prev << 25)) & 4294967295;
    var r0_b = ((prev >> 18) | (prev << 14)) & 4294967295;
    var r0_c = prev >> 3;
    return (r0_a ^ r0_b ^ r0_c) & 4294967295;
}

fn expand_s1(prev) -> int {
    /* ROTR(17,x) ^ ROTR(19,x) ^ SHR(10,x). */
    var r1_a = ((prev >> 17) | (prev << 15)) & 4294967295;
    var r1_b = ((prev >> 19) | (prev << 13)) & 4294967295;
    var r1_c = prev >> 10;
    return (r1_a ^ r1_b ^ r1_c) & 4294967295;
}

/* ---------------------------------------------------------------------------
 * sha256(data) — full SHA-256 implementation in pure newlang.
 *
 * Uses a mutable array for the message schedule W[0..63] and subscript
 * access to read round constants K[t].  All 64 compression rounds are
 * expressed as a while-loop with bitwise operations only.
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
    var H0 = 1779033703;
    var H1 = 3144134277;
    var H2 = 1013904242;
    var H3 = 2773480762;
    var H4 = 1359893119;
    var H5 = 2600822924;
    var H6 = 528734635;
    var H7 = 1541459225;

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

        /* --- Initialize working variables from current hash state. --- */
        var a = H0;
        var b = H1;
        var c = H2;
        var d = H3;
        var e = H4;
        var f = H5;
        var g = H6;
        var h = H7;

        /* --- 64 compression rounds using K[t] and W[t]. --- */
        var t = 0;
        while (t < 64) {
            /* S1(e) = ROTR(6,e) ^ ROTR(11,e) ^ ROTR(25,e). */
            var s1 = (((e >> 6) | (e << 26)) & 4294967295 ^
                       ((e >> 11) | (e << 21)) & 4294967295 ^
                       ((e >> 25) | (e << 7)) & 4294967295);

            /* ch(e,f,g) = (e & f) ^ (~e & g). */
            var ch = (e & f) ^ (~e & g);

            /* t1 = h + S1 + ch + K[t] + W[t]. */
            var t1 = (h + s1 + ch + K[t] + W[t]) & 4294967295;

            /* S0(a) = ROTR(2,a) ^ ROTR(13,a) ^ ROTR(22,a). */
            var s0 = (((a >> 2) | (a << 30)) & 4294967295 ^
                       ((a >> 13) | (a << 19)) & 4294967295 ^
                       ((a >> 22) | (a << 10)) & 4294967295);

            /* maj(a,b,c) = (a & b) ^ (a & c) ^ (b & c). */
            var maj = (a & b) ^ (a & c) ^ (b & c);

            /* t2 = S0 + maj. */
            var t2 = (s0 + maj) & 4294967295;

            /* Shift working variables and recurse. */
            h ← g;
            g ← f;
            f ← e;
            e ← (d + t1) & 4294967295;
            d ← c;
            c ← b;
            b ← a;
            a ← (t1 + t2) & 4294967295;

            t ← t + 1;
        }

        /* --- Add compressed chunk to current hash state. --- */
        H0 ← (H0 + a) & 4294967295;
        H1 ← (H1 + b) & 4294967295;
        H2 ← (H2 + c) & 4294967295;
        H3 ← (H3 + d) & 4294967295;
        H4 ← (H4 + e) & 4294967295;
        H5 ← (H5 + f) & 4294967295;
        H6 ← (H6 + g) & 4294967295;
        H7 ← (H7 + h) & 4294967295;

        blk_off ← blk_off + 64;
    }

    /* Return packed final hash: H0<<224 | ... | H7. */
    return (H0 << 224) | (H1 << 192) | (H2 << 160) | (H3 << 128) |
           (H4 << 96) | (H5 << 64) | (H6 << 32) | H7;
}

@start
fn main() -> none {
    var dir = std.fs.cwd();
    var file = dir.openFile("CLAUDE.md");
    var data = file.read_file(std.heap.allocator());
    var hash = sha256(data);
    std.print(hash);
}
