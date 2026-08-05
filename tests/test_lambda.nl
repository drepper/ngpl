// test_lambda.nl — tests for anonymous functions (λ) and currying

// Basic lambda: identity
@test
fn test_lambda_identity:
  var f = λx : int -> int: x
  assert_eq(42, f(42))

// Lambda with arithmetic
@test
fn test_lambda_add_one:
  var f = λx : int -> int: x + 1
  assert_eq(6, f(5))

// Multi-parameter lambda
@test
fn test_lambda_multi_param:
  var f = λx : int, y : int -> int: x + y
  assert_eq(7, f(3, 4))

// Lambda with capture
@test
fn test_lambda_capture:
  var offset = 10
  var f = λx : int |offset| -> int: x + offset
  assert_eq(15, f(5))

// Lambda with multiple captures
@test
fn test_lambda_multi_capture:
  var a = 3
  var b = 7
  var f = λx : int |a, b| -> int: x + a + b
  assert_eq(20, f(10))

// Lambda calling builtin (no capture needed)
@test
fn test_lambda_builtin_access:
  var f = λx : int, y : int -> int: x + y
  assert_eq(10, f(4, 6))

// Lambda as argument to another function
fn apply f, x: i32 -> i32:
  f(x)

@test
fn test_lambda_as_arg:
  var double = λx : int -> int: x * 2
  assert_eq(10, apply(double, 5))

// Lambda returned from a function
fn make_adder n: i32:
  λx : int |n| -> int: x + n

@test
fn test_lambda_return:
  var add3 = make_adder(3)
  assert_eq(8, add3(5))
  assert_eq(13, add3(10))

// Currying: partial application
fn add a: i32, b: i32 -> i32:
  a + b

@test
fn test_curry_basic:
  var add5 = add(5)
  assert_eq(8, add5(3))
  assert_eq(15, add5(10))

// Currying with 3 params
fn add3 a: i32, b: i32, c: i32 -> i32:
  a + b + c

@test
fn test_curry_three_params:
  var f1 = add3(1)
  var f2 = f1(2)
  assert_eq(6, f2(3))

// Immediate lambda call
@test
fn test_lambda_immediate:
  var result = (λx : int -> int: x + 1)(5)
  assert_eq(6, result)

// Lambda currying: partial application of lambda
@test
fn test_lambda_partial:
  var f = λx : int, y : int -> int: x * y
  var double = f(2)
  assert_eq(10, double(5))
  assert_eq(14, double(7))

// No capture list but references external
@test
@expect error "no capture list"
fn test_lambda_no_capture_list:
  var val = 10
  var f = λx : int -> int: x + val

// Undefined capture causes error
@test
@expect error "not defined"
fn test_lambda_undefined_capture:
  var f = λx : int |nonexistent| -> int: x

// Warning on ignored lambda (from currying)
@test
@expect warning "not used"
fn test_ignored_curry_warning:
  add(5)

// Warning on ignored lambda literal
@test
@expect warning "not used"
fn test_ignored_lambda_warning:
  λx : int -> int: x + 1

// Non-replaceable function accessible without capture
fn helper x: i32 -> i32:
  x + 100

@test
fn test_lambda_nonreplaceable_func:
  var f = λx : int -> int: helper(x)
  assert_eq(105, f(5))

// Replaceable function requires capture
@replaceable
fn mutable_fn x: i32 -> i32:
  x * 2

@test
fn test_lambda_replaceable_captured:
  var f = λx : int |mutable_fn| -> int: mutable_fn(x)
  assert_eq(10, f(5))

// Replaceable function without capture causes error
@test
@expect error "no capture list"
fn test_lambda_replaceable_uncaptured:
  var f = λx : int -> int: mutable_fn(x)

// Empty capture list is not allowed
@test
@expect error "empty capture list"
fn test_lambda_empty_capture_list:
  var f = λx : int || -> int: x * 2

// Missing type annotation causes error
@test
@expect error "requires a type"
fn test_lambda_missing_type:
  var f = λx |y| -> int: x + 1

// Missing return type causes error
@test
@expect error "return type"
fn test_lambda_missing_return_type:
  var f = λx : int: x + 1

@start
fn main:
  0
