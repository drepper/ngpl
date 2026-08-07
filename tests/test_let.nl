/* Test let bindings: immutability, typed, expressions. */

/* Basic let definition. */
@test
fn test_let_basic() → ∅:
    let x := 42
    assert_eq(x, 42)

/* Typed let definition. */
@test
fn test_let_typed() → ∅:
    let y : u32 = 100
    assert_eq(y, 100)

/* Let binding used in expressions. */
@test
fn test_let_in_expr() → ∅:
    let a := 10
    let b := 20
    let c : mut = a + b
    assert_eq(c, 30)

/* Let re-binding across loop iterations. */
@test
fn test_let_in_loop() → ∅:
    let sum : mut = 0
    foreach i := 1…5:
        let doubled := i * 2
        sum ← sum + doubled
    assert_eq(sum, 30)

@start
fn main() → ∅:
    std.print("let tests passed")
