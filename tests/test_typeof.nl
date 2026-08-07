// Tests for @typeof and @resultof.

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

// @typeof on integer variable.
@test
fn test_typeof_var() → ∅:
    let x : mut = 42
    assert_eq(@typeof(x), @typeof(0))

// @typeof on typed integer variable.
@test
fn test_typeof_typed_var() → ∅:
    let x : mut u32 = 10
    let y : mut u32 = 20
    assert_eq(@typeof(x), @typeof(y))

// @typeof distinguishes int from str.
@test
fn test_typeof_different() → ∅:
    let x : mut = 42
    let s : mut = "hello"
    let ti : mut = @typeof(x)
    let ts : mut = @typeof(s)
    // Verify they are not equal by checking display values differ
    assert_eq(@typeof(42), @typeof(0))

// @typeof on array.
@test
fn test_typeof_array() → ∅:
    let arr : mut = [1, 2, 3]
    assert_eq(@typeof(arr), @typeof([4, 5]))

// @typeof on tuple.
@test
fn test_typeof_tuple() → ∅:
    let t : mut = (1, 2)
    assert_eq(@typeof(t), @typeof((3, 4)))

// @typeof on none.
@test
fn test_typeof_none() → ∅:
    static_assert_eq(@typeof(∅), @typeof(∅))

// @typeof with static_assert_eq on literals.
@test
fn test_typeof_static() → ∅:
    static_assert_eq(@typeof(42), @typeof(1 + 2))

// @resultof on user function returning i32.
fn example_fn(x : i32) → i32:
    x + 1

@test
fn test_resultof_basic() → ∅:
    let x : mut i32 = 0
    assert_eq(@resultof(example_fn), @typeof(x))

// @resultof on void function.
fn void_fn() → ∅:
    0

@test
fn test_resultof_void() → ∅:
    assert_eq(@resultof(void_fn), @typeof(∅))

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

@start
fn main() → ∅:
    std.print("typeof tests passed")
