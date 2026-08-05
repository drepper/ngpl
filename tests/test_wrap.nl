/* Tests for @wrap annotation — explicit wrapping arithmetic.
 *
 * @wrap(expr) enables modular arithmetic for all operations within
 * the wrapped expression, even for signed types that normally abort
 * on overflow.
 */

/* ---- @wrap on signed types: wraps instead of aborting -------------------- */

@test
fn test_wrap_i8_add -> ∅:
    var x : i8 = 127
    var y : i8 = 1
    var z := @wrap(x + y)
    assert_eq(z, -128)

@test
fn test_wrap_i8_sub -> ∅:
    var x : i8 = -128
    var y : i8 = 1
    var z := @wrap(x - y)
    assert_eq(z, 127)

@test
fn test_wrap_i8_mul -> ∅:
    var x : i8 = 64
    var y : i8 = 4
    var z := @wrap(x * y)
    assert_eq(z, 0)

@test
fn test_wrap_i32_add -> ∅:
    var x : i32 = 2147483647
    var y : i32 = 1
    var z := @wrap(x + y)
    assert_eq(z, -2147483648)

@test
fn test_wrap_i32_negate -> ∅:
    var x : i32 = -2147483648
    var z := @wrap(-x)
    assert_eq(z, -2147483648)

/* ---- @wrap on unsigned types: still wraps as expected -------------------- */

@test
fn test_wrap_u32_add -> ∅:
    var x : u32 = 4294967295
    var y : u32 = 2
    var z := @wrap(x + y)
    assert_eq(z, 1)

/* ---- @wrap does not affect operations outside its scope ----------------- */

@expect error "integer overflow"
fn error_no_wrap_i8 -> ∅:
    var x : i8 = 127
    var y : i8 = 1
    /* @wrap only on the subtraction, not the addition */
    var dummy := @wrap(x - y)
    var z := x + y

/* ---- @wrap with complex expressions ------------------------------------- */

@test
fn test_wrap_chained_add -> ∅:
    var a : i8 = 100
    var b : i8 = 100
    var c : i8 = 100
    var z := @wrap(a + b + c)
    assert_eq(z, 44)

@start
fn main -> ∅:
    std.print("wrap tests passed")
