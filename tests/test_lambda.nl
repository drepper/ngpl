// test_lambda.nl — tests for anonymous functions (λ) and currying

// Basic lambda: identity
@test
fn test_lambda_identity():
  let f := λx : int → int: x
  assert_eq(42, f(42))

// Lambda with arithmetic
@test
fn test_lambda_add_one():
  let f := λx : int → int: x + 1
  assert_eq(6, f(5))

// Multi-parameter lambda
@test
fn test_lambda_multi_param():
  let f := λx : int, y : int → int: x + y
  assert_eq(7, f(3, 4))

// Lambda with capture
@test
fn test_lambda_capture():
  let offset := 10
  let f := λx : int |offset| → int: x + offset
  assert_eq(15, f(5))

// Lambda with multiple captures
@test
fn test_lambda_multi_capture():
  let a := 3
  let b := 7
  let f := λx : int |a, b| → int: x + a + b
  assert_eq(20, f(10))

// Lambda calling builtin (no capture needed)
@test
fn test_lambda_builtin_access():
  let f := λx : int, y : int → int: x + y
  assert_eq(10, f(4, 6))

// Lambda as argument to another function
fn apply(f, x: i32) → i32:
  f(x)

@test
fn test_lambda_as_arg():
  let double := λx : int → int: x × 2
  assert_eq(10, apply(double, 5))

// Lambda returned from a function
fn make_adder(n: i32):
  λx : int |n| → int: x + n

@test
fn test_lambda_return():
  let add3 := make_adder(3)
  assert_eq(8, add3(5))
  assert_eq(13, add3(10))

// Currying: partial application
fn add(a: i32, b: i32) → i32:
  a + b

@test
fn test_curry_basic():
  let add5 := add(5)
  assert_eq(8, add5(3))
  assert_eq(15, add5(10))

// Currying with 3 params
fn add3(a: i32, b: i32, c: i32) → i32:
  a + b + c

@test
fn test_curry_three_params():
  let f1 := add3(1)
  let f2 := f1(2)
  assert_eq(6, f2(3))

// Immediate lambda call
@test
fn test_lambda_immediate():
  let result := (λx : int → int: x + 1)(5)
  assert_eq(6, result)

// Lambda currying: partial application of lambda
@test
fn test_lambda_partial():
  let f := λx : int, y : int → int: x × y
  let double := f(2)
  assert_eq(10, double(5))
  assert_eq(14, double(7))

// No capture list but references external
@test
@expect error "no capture list"
fn test_lambda_no_capture_list():
  let val : mut = 10
  let f : mut = λx : int → int: x + val

// Undefined capture causes error
@test
@expect error "not defined"
fn test_lambda_undefined_capture():
  let f : mut = λx : int |nonexistent| → int: x

// Warning on ignored lambda (from currying)
@test
@expect warning "not used"
fn test_ignored_curry_warning():
  add(5)

// Warning on ignored lambda literal
@test
@expect warning "not used"
fn test_ignored_lambda_warning():
  λx : int → int: x + 1

// Non-replaceable function accessible without capture
fn helper(x: i32) → i32:
  x + 100

@test
fn test_lambda_nonreplaceable_func():
  let f := λx : int → int: helper(x)
  assert_eq(105, f(5))

// Replaceable function requires capture
@replaceable
fn mutable_fn(x: i32) → i32:
  x × 2

@test
fn test_lambda_replaceable_captured():
  let f := λx : int |mutable_fn| → int: mutable_fn(x)
  assert_eq(10, f(5))

// Replaceable function without capture causes error
@test
@expect error "no capture list"
fn test_lambda_replaceable_uncaptured():
  let f : mut = λx : int → int: mutable_fn(x)

// Empty capture list is not allowed
@test
@expect error "empty capture list"
fn test_lambda_empty_capture_list():
  let f : mut = λx : int || → int: x × 2

// Optional return type wraps result in Some
@test
fn test_lambda_optional_return():
  let f := λx : int → int?: x + 1
  let r := f(5)
  assert_eq(6, r ?? 0)

// Optional return type: body returning ∅ stays ∅
@test
fn test_lambda_optional_return_none():
  let f := λx : int → int?: ∅
  let r := f(0)
  assert_eq(42, r ?? 42)

// ? inside lambda returns from lambda, not enclosing function
fn safe_div(a : i32, b : i32) → i32?:
  if b == 0: return ∅
  a / b

@test
fn test_lambda_question_scoping():
  let f := λa : int, b : int |safe_div| → int?: safe_div(a, b)?
  assert_eq(5, f(10, 2) ?? 0)
  assert_eq(0, f(10, 0) ?? 0)

// Expected return type wraps result in ExpectedValue.ok
@test
fn test_lambda_expected_return():
  let f := λa : int, b : int → int!: (a / b)?
  let r := f(10, 2)
  assert_eq(5, r ?? ⁻1)

// Expected return type: division by zero yields error
@test
fn test_lambda_expected_return_err():
  let f := λa : int, b : int → int!: (a / b)?
  let r := f(10, 0)
  assert_eq(⁻1, r ?? ⁻1)

// Missing type annotation causes error
@test
@expect error "requires a type"
fn test_lambda_missing_type():
  let f : mut = λx |y| → int: x + 1

// Missing return type causes error
@test
@expect error "return type"
fn test_lambda_missing_return_type():
  let f : mut = λx : int: x + 1

// Multi-statement lambda with layout block
@test
fn test_lambda_multi_stmt_layout() → ∅:
  let f := λx : int → int:
    let y := x × 2
    y + 1
  assert_eq(11, f(5))

// Multi-statement lambda with brace block
@test
fn test_lambda_multi_stmt_brace() → ∅:
  let f := λx : int → int: {
    let y := x + 10;
    let z := y × 2;
    z
  }
  assert_eq(30, f(5))

// Multi-statement lambda with early return
@test
fn test_lambda_multi_stmt_return() → ∅:
  let f := λx : int → int:
    if x < 0:
      return 0
    x × x
  assert_eq(25, f(5))
  assert_eq(0, f(⁻3))

// Multi-statement lambda with capture
@test
fn test_lambda_multi_stmt_capture() → ∅:
  let base := 100
  let f := λx : int |base| → int:
    let doubled := x × 2
    base + doubled
  assert_eq(110, f(5))

// Multi-statement lambda with loop
@test
fn test_lambda_multi_stmt_loop() → ∅:
  let f := λn : int → int:
    let sum : mut = 0
    foreach i := 1…n:
      sum ← sum + i
    sum
  assert_eq(55, f(10))

// Multi-statement lambda as argument (braces required inside parens)
@test
fn test_lambda_multi_stmt_as_arg() → ∅:
  let result := apply(λx : int → int: {
    let a := x + 1;
    a × 2
  }, 4)
  assert_eq(10, result)

@start
fn main():
  0
