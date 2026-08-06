/* Test layout-driven scoping, mixed mode, and edge cases. */

fn abs_layout x : int → int:
    if x < 0: return ⁻x
    x

fn abs_brace x : int → int {
    if x < 0 { return ⁻x; }
    x
}

fn fib n : int → int:
    if n <= 1: return n
    fib(n - 1) + fib(n - 2)

/* Mixed: layout function body, brace block inside. */
fn mixed_test x : int → int:
    if x > 10 {
        return x - 10;
    }
    x

/* Mixed: brace function body, layout block inside. */
fn mixed_test2 x : int → int {
    if x > 10:
        return x - 10
    x
}

@test
fn test_abs → ∅:
    assert_eq(abs_layout(5), 5)
    assert_eq(abs_layout(⁻3), 3)
    assert_eq(abs_brace(5), 5)
    assert_eq(abs_brace(⁻3), 3)

@test
fn test_fib → ∅:
    assert_eq(fib(0), 0)
    assert_eq(fib(1), 1)
    assert_eq(fib(10), 55)

@test
fn test_mixed → ∅:
    assert_eq(mixed_test(15), 5)
    assert_eq(mixed_test(5), 5)
    assert_eq(mixed_test2(15), 5)
    assert_eq(mixed_test2(5), 5)

@start
fn main → ∅:
    std.print("layout tests passed")
