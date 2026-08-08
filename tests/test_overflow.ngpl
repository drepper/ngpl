// Tests for integer overflow/underflow detection.
//
// Unsigned types wrap silently (modular arithmetic).
// Signed types and untyped-to-signed coercion raise OverflowError.

// ---- static: assignment overflow -----------------------------------------

@expect error "integer overflow.*does not fit in i8"
fn error_i8_too_large() → ∅:
    let x : mut i8 = 128

@expect error "integer overflow.*does not fit in i8"
fn error_i8_too_small() → ∅:
    let x : mut i8 = ⁻129

@expect error "integer overflow.*does not fit in i16"
fn error_i16_too_large() → ∅:
    let x : mut i16 = 32768

@expect error "integer overflow.*does not fit in i32"
fn error_i32_too_large() → ∅:
    let x : mut i32 = 2147483648

@expect error "integer overflow.*does not fit in i64"
fn error_i64_too_large() → ∅:
    let x : mut i64 = 9223372036854775808

// ---- static: unsigned assignment wraps -----------------------------------

@test
fn test_u8_wraps_on_assign() → ∅:
    let x : u8 = 256
    assert_eq(x, 0)

@test
fn test_u8_wraps_negative() → ∅:
    let x : u8 = ⁻1
    assert_eq(x, 255)

@test
fn test_u32_wraps_on_assign() → ∅:
    let x : u32 = 4294967296
    assert_eq(x, 0)

// ---- dynamic: signed arithmetic overflow ---------------------------------

@expect error "integer overflow"
fn error_i8_add_overflow() → ∅:
    let x : mut i8 = 127
    let y : mut i8 = 1
    let z : mut = x + y

@expect error "integer overflow"
fn error_i8_sub_underflow() → ∅:
    let x : mut i8 = ⁻128
    let y : mut i8 = 1
    let z : mut = x - y

@expect error "integer overflow"
fn error_i16_mul_overflow() → ∅:
    let x : mut i16 = 200
    let y : mut i16 = 200
    let z : mut = x × y

@expect error "integer overflow"
fn error_i32_add_overflow() → ∅:
    let x : mut i32 = 2147483647
    let y : mut i32 = 1
    let z : mut = x + y

@expect error "integer overflow"
fn error_i32_negate_min() → ∅:
    let x : mut i32 = ⁻2147483648
    let z : mut = ⁻x

// ---- dynamic: unsigned arithmetic wraps ----------------------------------

@test
fn test_u8_add_wraps() → ∅:
    let x : u8 = 255
    let y : u8 = 1
    let z := x + y
    assert_eq(z, 0)

@test
fn test_u8_sub_wraps() → ∅:
    let x : u8 = 0
    let y : u8 = 1
    let z := x - y
    assert_eq(z, 255)

@test
fn test_u32_add_wraps() → ∅:
    let x : u32 = 4294967295
    let y : u32 = 1
    let z := x + y
    assert_eq(z, 0)

@test
fn test_u32_mul_wraps() → ∅:
    let x : u32 = 65536
    let y : u32 = 65536
    let z := x × y
    assert_eq(z, 0)

// ---- boundary values: signed types ---------------------------------------

@test
fn test_i8_max() → ∅:
    let x : i8 = 127
    assert_eq(x, 127)

@test
fn test_i8_min() → ∅:
    let x : i8 = ⁻128
    assert_eq(x, ⁻128)

@test
fn test_i32_max() → ∅:
    let x : i32 = 2147483647
    assert_eq(x, 2147483647)

@test
fn test_i32_min() → ∅:
    let x : i32 = ⁻2147483648
    assert_eq(x, ⁻2147483648)

// ---- bitwise ops always wrap (not overflow) ------------------------------

@test
fn test_bitwise_not_i8() → ∅:
    let x : i8 = 0
    let y := ~x
    assert_eq(y, ⁻1)

@test
fn test_shift_left_wraps() → ∅:
    let x : u8 = 128
    let s : u8 = 1
    let y := x « s
    assert_eq(y, 0)

@start
fn main() → ∅:
    std.print("overflow tests passed")
