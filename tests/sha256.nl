/* SHA-256 implemented entirely in newlang using bitwise operators. */
/* No std helpers — all logic is pure newlang with arrays. */

/* ---------------------------------------------------------------------------
 * Static round constants K[0..63] — initialized once, read-only.
 * Each value fits in a signed 64-bit integer for the interpreter.
 * --------------------------------------------------------------------------- */

const K : u32 = [
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
 * SHA-256 padding helpers.
 *
 * SHA-256 padding requires a 0x80 byte after the message and a big-endian
 * 64-bit bit-length suffix.  These helpers overlay the padding on reads
 * beyond the original data.
 * --------------------------------------------------------------------------- */

fn get_padded_byte data : byte[], pos : usize, total_size : usize -> u8?:
    if pos >= total_size: return none
    if pos < data.sizeof: return data[pos]
    if pos == data.sizeof: return 128
    var len_start := total_size - 8
    if pos >= len_start:
        const bit_len := data.sizeof * 8
        const byte_idx := pos - len_start
        return (bit_len » ((7 - byte_idx) * 8)) & 255
    none

fn get_padded_word data : byte[], off : usize, total_size : usize -> u32?:
    if off + 4 <= data.sizeof:
        const b0 : u32 = data[off]
        const b1 : u32 = data[off + 1]
        const b2 : u32 = data[off + 2]
        const b3 : u32 = data[off + 3]
        return (b0 « 24) | (b1 « 16) | (b2 « 8) | b3
    if off >= total_size: return none
    const b0 : u32 = get_padded_byte(data, off, total_size) ?? 0
    const b1 : u32 = get_padded_byte(data, off + 1, total_size) ?? 0
    const b2 : u32 = get_padded_byte(data, off + 2, total_size) ?? 0
    const b3 : u32 = get_padded_byte(data, off + 3, total_size) ?? 0
    (b0 « 24) | (b1 « 16) | (b2 « 8) | b3

/* ---------------------------------------------------------------------------
 * SHA-256 sigma helpers for message-schedule expansion.
 * --------------------------------------------------------------------------- */

fn expand_Σ₀ prev : u32 -> u32:
    (prev ↻ 7) ^ (prev ↻ 18) ^ (prev » 3)

fn expand_Σ₁ prev : u32 -> u32:
    (prev ↻ 17) ^ (prev ↻ 19) ^ (prev » 10)

/* ---------------------------------------------------------------------------
 * sha256(data) — full SHA-256 implementation in pure newlang.
 *
 * Uses « » for shifts, ↺ ↻ for rotations, and subscript access for the
 * message schedule W[0..63] and round constants K[t].
 * --------------------------------------------------------------------------- */

fn sha256 data : byte[] -> int?:
    /* Compute padded message length per SHA-256 spec. */
    const rem : usize = data.sizeof % 64
    const pad_len : usize = (119 - rem) % 64
    const total_size : usize = data.sizeof + 1 + pad_len + 8

    /* Initial hash values per FIPS 180-4 Section 5.3.3. */
    var H : u32 = [
        1779033703, 3144134277, 1013904242, 2773480762,
        1359893119, 2600822924, 528734635,  1541459225,
    ]

    /* Process each 64-byte block. */
    foreach blk_off : usize = 0…64…(total_size - 1):
        /* --- Load W[0..15] from the current block (with padding overlay). --- */
        var W : u32[64] = 0
        foreach i : u32fast = 0…15:
            W[i] ← get_padded_word(data, blk_off + (i * 4), total_size)?

        /* --- Message-schedule expansion: W[16..63]. --- */
        foreach j : u32fast = 16…63:
            W[j] ← @wrap(W[j - 16] + expand_Σ₀(W[j - 15]) +
                         W[j - 7] + expand_Σ₁(W[j - 2]))

        /* --- Working variables: copy of current hash state. --- */
        var v := H[0…7]

        /* --- 64 compression rounds using K[t] and W[t]. --- */
        foreach t : u32fast = 0…63:
            /* Σ₁(e) = ROTR(6,e) ⊕ ROTR(11,e) ⊕ ROTR(25,e). */
            const Σ₁ := (v[4] ↻ 6) ^ (v[4] ↻ 11) ^ (v[4] ↻ 25)

            /* ch(e,f,g) = (e ∧ f) ⊕ (¬e ∧ g). */
            const ch := (v[4] & v[5]) ^ (~v[4] & v[6])

            /* t1 = h + Σ₁ + ch + K[t] + W[t]. */
            const t1 := @wrap(v[7] + Σ₁ + ch + K[t] + W[t])

            /* Σ₀(a) = ROTR(2,a) ⊕ ROTR(13,a) ⊕ ROTR(22,a). */
            const Σ₀ := (v[0] ↻ 2) ^ (v[0] ↻ 13) ^ (v[0] ↻ 22)

            /* maj(a,b,c) = (a ∧ b) ⊕ (a ∧ c) ⊕ (b ∧ c). */
            const maj := (v[0] & v[1]) ^ (v[0] & v[2]) ^ (v[1] & v[2])

            /* t2 = Σ₀ + maj. */
            const t2 := @wrap(Σ₀ + maj)

            /* Shift working variables right by one position. */
            v[1…7] ← v[0…6]
            v[0] ← @wrap(t1 + t2)
            v[4] ← @wrap(v[4] + t1)

        /* --- Add compressed chunk to current hash state. --- */
        H ← @wrap(H + v)

    /* Pack final hash: H[0]«224 | … | H[7]. */
    var hash := 0
    foreach h = H:
        hash ← (hash « 32) | h
    hash

/* ---------------------------------------------------------------------------
 * Unit tests — FIPS 180-4 test vectors for SHA-256.
 *
 * @test(sha256) marks these as tests for the sha256 function: they run
 * automatically on the first call to sha256.
 * --------------------------------------------------------------------------- */

@test(sha256)
fn test_sha256_empty -> none:
    var data := std.bytes("")
    var hash := sha256(data)
    assert_eq(hash, 0xe3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855)

@test(sha256)
fn test_sha256_abc -> none:
    var data := std.bytes("abc")
    var hash := sha256(data)
    assert_eq(hash, 0xba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad)

@test(sha256)
fn test_sha256_448bit -> none:
    var data := std.bytes("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq")
    var hash := sha256(data)
    assert_eq(hash, 0x248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1)

@start
fn main -> none:
    var dir := std.fs.cwd()
    var file := dir.openFile("CLAUDE.md")
    var data := file.read_file(std.heap.allocator())
    var hash := sha256(data)
    std.print(hash)
