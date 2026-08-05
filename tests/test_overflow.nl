/* Tests for integer overflow/underflow detection.
 *
 * Unsigned types wrap silently (modular arithmetic).
 * Signed types and untyped-to-signed coercion raise OverflowError.
 */

/* ---- static: assignment overflow ----------------------------------------- */

@expect error "integer overflow.*does not fit in i8"
fn error_i8_too_large -> none:
    var x : i8 = 128

@expect error "integer overflow.*does not fit in i8"
fn error_i8_too_small -> none:
    var x : i8 = -129

@expect error "integer overflow.*does not fit in i16"
fn error_i16_too_large -> none:
    var x : i16 = 32768

@expect error "integer overflow.*does not fit in i32"
fn error_i32_too_large -> none:
    var x : i32 = 2147483648

@expect error "integer overflow.*does not fit in i64"
fn error_i64_too_large -> none:
    var x : i64 = 9223372036854775808

/* ---- static: unsigned assignment wraps ----------------------------------- */

@test
fn test_u8_wraps_on_assign -> none:
    var x : u8 = 256
    assert_eq(x, 0)

@test
fn test_u8_wraps_negative -> none:
    var x : u8 = -1
    assert_eq(x, 255)

@test
fn test_u32_wraps_on_assign -> none:
    var x : u32 = 4294967296
    assert_eq(x, 0)

/* ---- dynamic: signed arithmetic overflow --------------------------------- */

@expect error "integer overflow"
fn error_i8_add_overflow -> none:
    var x : i8 = 127
    var y : i8 = 1
    var z := x + y

@expect error "integer overflow"
fn error_i8_sub_underflow -> none:
    var x : i8 = -128
    var y : i8 = 1
    var z := x - y

@expect error "integer overflow"
fn error_i16_mul_overflow -> none:
    var x : i16 = 200
    var y : i16 = 200
    var z := x * y

@expect error "integer overflow"
fn error_i32_add_overflow -> none:
    var x : i32 = 2147483647
    var y : i32 = 1
    var z := x + y

@expect error "integer overflow"
fn error_i32_negate_min -> none:
    var x : i32 = -2147483648
    var z := -x

/* ---- dynamic: unsigned arithmetic wraps ---------------------------------- */

@test
fn test_u8_add_wraps -> none:
    var x : u8 = 255
    var y : u8 = 1
    var z := x + y
    assert_eq(z, 0)

@test
fn test_u8_sub_wraps -> none:
    var x : u8 = 0
    var y : u8 = 1
    var z := x - y
    assert_eq(z, 255)

@test
fn test_u32_add_wraps -> none:
    var x : u32 = 4294967295
    var y : u32 = 1
    var z := x + y
    assert_eq(z, 0)

@test
fn test_u32_mul_wraps -> none:
    var x : u32 = 65536
    var y : u32 = 65536
    var z := x * y
    assert_eq(z, 0)

/* ---- boundary values: signed types --------------------------------------- */

@test
fn test_i8_max -> none:
    var x : i8 = 127
    assert_eq(x, 127)

@test
fn test_i8_min -> none:
    var x : i8 = -128
    assert_eq(x, -128)

@test
fn test_i32_max -> none:
    var x : i32 = 2147483647
    assert_eq(x, 2147483647)

@test
fn test_i32_min -> none:
    var x : i32 = -2147483648
    assert_eq(x, -2147483648)

/* ---- bitwise ops always wrap (not overflow) ------------------------------ */

@test
fn test_bitwise_not_i8 -> none:
    var x : i8 = 0
    var y := ~x
    assert_eq(y, -1)

@test
fn test_shift_left_wraps -> none:
    var x : u8 = 128
    var s : u8 = 1
    var y := x « s
    assert_eq(y, 0)

@start
fn main -> none:
    std.print("overflow tests passed")
