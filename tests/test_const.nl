/* Test const local variables: immutability, typed, expressions. */

/* Basic const definition. */
@test
fn test_const_basic -> ∅:
    const x := 42
    assert_eq(x, 42)

/* Typed const definition. */
@test
fn test_const_typed -> ∅:
    const y : u32 = 100
    assert_eq(y, 100)

/* Const used in expressions. */
@test
fn test_const_in_expr -> ∅:
    const a := 10
    const b := 20
    var c := a + b
    assert_eq(c, 30)

/* Const re-binding across loop iterations. */
@test
fn test_const_in_loop -> ∅:
    var sum := 0
    foreach i := 1…5:
        const doubled := i * 2
        sum ← sum + doubled
    assert_eq(sum, 30)

@start
fn main -> ∅:
    std.print("const tests passed")
