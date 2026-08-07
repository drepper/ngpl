// Tests for @wrap annotation — explicit wrapping arithmetic.
//
// @wrap(expr) enables modular arithmetic for all operations within
// the wrapped expression, even for signed types that normally abort
// on overflow.

// ---- @wrap on signed types: wraps instead of aborting --------------------

@test
fn test_wrap_i8_add() → ∅:
    let x : mut i8 = 127
    let y : mut i8 = 1
    let z : mut = @wrap(x + y)
    assert_eq(z, ⁻128)

@test
fn test_wrap_i8_sub() → ∅:
    let x : mut i8 = ⁻128
    let y : mut i8 = 1
    let z : mut = @wrap(x - y)
    assert_eq(z, 127)

@test
fn test_wrap_i8_mul() → ∅:
    let x : mut i8 = 64
    let y : mut i8 = 4
    let z : mut = @wrap(x * y)
    assert_eq(z, 0)

@test
fn test_wrap_i32_add() → ∅:
    let x : mut i32 = 2147483647
    let y : mut i32 = 1
    let z : mut = @wrap(x + y)
    assert_eq(z, ⁻2147483648)

@test
fn test_wrap_i32_negate() → ∅:
    let x : mut i32 = ⁻2147483648
    let z : mut = @wrap(⁻x)
    assert_eq(z, ⁻2147483648)

// ---- @wrap on unsigned types: still wraps as expected --------------------

@test
fn test_wrap_u32_add() → ∅:
    let x : mut u32 = 4294967295
    let y : mut u32 = 2
    let z : mut = @wrap(x + y)
    assert_eq(z, 1)

// ---- @wrap does not affect operations outside its scope -----------------

@expect error "integer overflow"
fn error_no_wrap_i8() → ∅:
    let x : mut i8 = 127
    let y : mut i8 = 1
    // @wrap only on the subtraction, not the addition
    let dummy : mut = @wrap(x - y)
    let z : mut = x + y

// ---- @wrap with complex expressions -------------------------------------

@test
fn test_wrap_chained_add() → ∅:
    let a : mut i8 = 100
    let b : mut i8 = 100
    let c : mut i8 = 100
    let z : mut = @wrap(a + b + c)
    assert_eq(z, 44)

@start
fn main() → ∅:
    std.print("wrap tests passed")
