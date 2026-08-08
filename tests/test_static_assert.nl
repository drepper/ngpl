// Tests for static_assert and static_assert_eq.

// Basic static_assert with true condition.
@test
fn test_static_assert_true() → ∅:
    static_assert(true)

// static_assert with integer expression.
@test
fn test_static_assert_int() → ∅:
    static_assert(1)

// static_assert with computed constant.
@test
fn test_static_assert_computed() → ∅:
    static_assert(2 + 3 == 5)

// static_assert_eq with equal integers.
@test
fn test_static_assert_eq_int() → ∅:
    static_assert_eq(42, 42)

// static_assert_eq with computed constants.
@test
fn test_static_assert_eq_computed() → ∅:
    static_assert_eq(10, 3 + 7)

// static_assert_eq with strings.
@test
fn test_static_assert_eq_str() → ∅:
    static_assert_eq("hello", "hello")

// static_assert_eq with booleans.
@test
fn test_static_assert_eq_bool() → ∅:
    static_assert_eq(true, true)

// static_assert with negation.
@test
fn test_static_assert_negation() → ∅:
    static_assert(⁻(⁻ 1))

// static_assert_eq with arithmetic.
@test
fn test_static_assert_eq_arithmetic() → ∅:
    static_assert_eq(120, 2 × 3 × 4 × 5)

// Error: static_assert with false.
@test
@expect error "static_assert failed"
fn test_static_assert_false() → ∅:
    static_assert(false)

// Error: static_assert with zero.
@test
@expect error "static_assert failed"
fn test_static_assert_zero() → ∅:
    static_assert(0)

// Error: static_assert with message.
@test
@expect error "static_assert failed.*should be true"
fn test_static_assert_message() → ∅:
    static_assert(false, "should be true")

// Error: static_assert_eq with unequal values.
@test
@expect error "static_assert_eq failed"
fn test_static_assert_eq_fail() → ∅:
    static_assert_eq(1, 2)

// Error: static_assert with non-constant expression.
@test
@expect error "compile-time constant"
fn test_static_assert_non_const() → ∅:
    let x : mut = 42
    static_assert(x)

// Error: static_assert_eq with non-constant.
@test
@expect error "compile-time constant"
fn test_static_assert_eq_non_const() → ∅:
    let x : mut = 10
    static_assert_eq(x, 10)

@start
fn main() → ∅:
    std.print("static_assert tests passed")
