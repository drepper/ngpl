/* Tests for currying (partial application) of functions and lambdas. */

/* --- Named function currying --- */

fn multiply a : int, b : int → int:
    a * b

/* Curry a named function to create a doubler. */
@test
fn test_curry_named_fn → ∅:
    var double := multiply(2)
    assert_eq(double(5), 10)
    assert_eq(double(7), 14)

/* Curry a named function and use it with generate. */
@test
fn test_curry_named_with_generate → ∅:
    var triple := multiply(3)
    var result := generate(triple, 1…5)
    assert_eq(result[0], 3)
    assert_eq(result[1], 6)
    assert_eq(result[2], 9)
    assert_eq(result[3], 12)
    assert_eq(result[4], 15)

/* Three-parameter function curried in stages. */
fn add3 a : int, b : int, c : int → int:
    a + b + c

@test
fn test_curry_staged → ∅:
    var f1 := add3(10)
    var f2 := f1(20)
    assert_eq(f2(30), 60)

/* Curry two arguments at once. */
@test
fn test_curry_two_at_once → ∅:
    var f := add3(100, 200)
    assert_eq(f(300), 600)

/* --- Lambda currying --- */

/* Curry a lambda to create a fixed-offset function. */
@test
fn test_curry_lambda → ∅:
    var add := λa : int, b : int → int: a + b
    var add10 := add(10)
    assert_eq(add10(5), 15)
    assert_eq(add10(25), 35)

/* Curry a lambda and use it with generate. */
@test
fn test_curry_lambda_with_generate → ∅:
    var power := λbase : int, exp : int → int: base * exp
    var times5 := power(5)
    var result := generate(times5, 0…4)
    assert_eq(result[0], 0)
    assert_eq(result[1], 5)
    assert_eq(result[2], 10)
    assert_eq(result[3], 15)
    assert_eq(result[4], 20)

/* Three-parameter lambda curried in stages. */
@test
fn test_curry_lambda_staged → ∅:
    var f := λa : int, b : int, c : int → int: a + b + c
    var f1 := f(1)
    var f2 := f1(2)
    assert_eq(f2(3), 6)

/* Curry a lambda with captures. */
@test
fn test_curry_lambda_with_capture → ∅:
    var offset := 100
    var add_offset := λx : int, y : int |offset| → int: x + y + offset
    var f := add_offset(50)
    assert_eq(f(10), 160)

/* --- Curried functions as first-class values --- */

/* Pass a curried function to another function. */
fn apply_and_sum f, arr : int[] → int:
    var total := 0
    foreach v := arr:
        total ← total + f(v)
    total

@test
fn test_curry_as_argument → ∅:
    var double := multiply(2)
    var result := apply_and_sum(double, [1, 2, 3, 4, 5])
    assert_eq(result, 30)

/* --- Curried functions with generate and fold --- */

fn add a : int, b : int → int:
    a + b

@test
fn test_curry_with_fold → ∅:
    var add5 := add(5)
    var arr := generate(add5, 0…4)
    /* arr = [5, 6, 7, 8, 9] */
    var total := ⌿(add, arr, 0)
    assert_eq(total, 35)

/* --- Error cases --- */

/* Too many arguments to a curried function. */
@test
@expect error "expects 2 arguments, got 3"
fn test_curry_too_many_args → ∅:
    var f := multiply(2)
    f(3, 4)

@start
fn main → ∅:
    std.print("curry tests passed")
