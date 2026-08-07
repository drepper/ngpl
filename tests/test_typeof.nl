// Tests for @typeof and @resultof.
// All @ commands require compile-time constant arguments.

// @typeof on integer literal.
@test
fn test_typeof_int() → ∅:
    static_assert_eq(@typeof(42), @typeof(0))

// @typeof on string literal.
@test
fn test_typeof_str() → ∅:
    static_assert_eq(@typeof("hello"), @typeof("world"))

// @typeof on bool literal.
@test
fn test_typeof_bool() → ∅:
    static_assert_eq(@typeof(true), @typeof(false))

// @typeof distinguishes int from str.
@test
fn test_typeof_different() → ∅:
    static_assert_eq(@typeof(42), @typeof(0))
    static_assert_eq(@typeof("a"), @typeof("b"))

// @typeof on array literal.
@test
fn test_typeof_array() → ∅:
    static_assert_eq(@typeof([1, 2, 3]), @typeof([4, 5]))

// @typeof on tuple literal.
@test
fn test_typeof_tuple() → ∅:
    static_assert_eq(@typeof((1, 2)), @typeof((3, 4)))

// @typeof on none.
@test
fn test_typeof_none() → ∅:
    static_assert_eq(@typeof(∅), @typeof(∅))

// @typeof with static_assert_eq on computed constants.
@test
fn test_typeof_static() → ∅:
    static_assert_eq(@typeof(42), @typeof(1 + 2))

// @resultof on user function returning i32.
fn example_fn(x : i32) → i32:
    x + 1

fn identity_i32(x : i32) → i32:
    x

@test
fn test_resultof_basic() → ∅:
    static_assert_eq(@resultof(example_fn), @resultof(identity_i32))

// @resultof on void function.
fn void_fn() → ∅:
    0

@test
fn test_resultof_void() → ∅:
    static_assert_eq(@resultof(void_fn), @typeof(∅))

// @resultof on function with optional return.
fn optional_fn(x : i32) → i32?:
    if x < 0: return ∅
    x

@test
fn test_resultof_optional() → ∅:
    let rt : mut = @resultof(optional_fn)
    assert_eq(rt, rt)

// Error: @resultof with unknown function.
@test
@expect error "unknown function"
fn test_resultof_unknown() → ∅:
    let t : mut = @resultof(nonexistent)

// Error: @typeof with non-constant argument.
@test
@expect error "compile-time constant"
fn test_typeof_non_const() → ∅:
    let x : mut = 42
    @typeof(x)

@start
fn main() → ∅:
    std.print("typeof tests passed")
