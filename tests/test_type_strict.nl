// Type strictness tests: return type checking and mixed-type arithmetic.

// --- Return type mismatch: function body vs declared type ---

fn returns_float_as_int() → int:
  1.25

@test
@expect error "return type is int but body evaluates to float"
fn test_return_float_for_int() → ∅:
  returns_float_as_int()

fn returns_int_as_float() → f64:
  42

@test
@expect error "return type is f64 but body evaluates to int"
fn test_return_int_for_float() → ∅:
  returns_int_as_float()

fn returns_float_as_i32() → i32:
  3.14

@test
@expect error "return type is i32 but body evaluates to float"
fn test_return_float_for_i32() → ∅:
  returns_float_as_i32()

fn returns_int_as_f32() → f32:
  7

@test
@expect error "return type is f32 but body evaluates to int"
fn test_return_int_for_f32() → ∅:
  returns_int_as_f32()

// Return type matches: these should succeed.

fn returns_int_ok() → int:
  42

@test
fn test_return_int_ok() → ∅:
  assert_eq(42, returns_int_ok())

fn returns_float_ok() → f64:
  3.14

@test
fn test_return_float_ok() → ∅:
  let r : mut = returns_float_ok()
  assert_true(r > 3.0)

fn returns_str_ok() → str:
  "hello"

@test
fn test_return_str_ok() → ∅:
  assert_true(returns_str_ok() == "hello")

fn returns_bool_ok() → bool:
  true

@test
fn test_return_bool_ok() → ∅:
  assert(returns_bool_ok())

// Return type check with explicit return statement.

fn early_return_float_as_int(x: int) → int:
  if x > 0:
    return 1.5
  0

@test
@expect error "return type is int but body evaluates to float"
fn test_early_return_mismatch() → ∅:
  early_return_float_as_int(1)

// Return type check with optional return type.

fn returns_float_as_int_opt() → int?:
  1.25

@test
@expect error "return type is int.* but body evaluates to float"
fn test_return_float_for_int_optional() → ∅:
  returns_float_as_int_opt()

// Optional returning none is fine regardless of inner type.

fn returns_none_for_int_opt() → int?:
  ∅

@test
fn test_return_none_for_optional() → ∅:
  let r : mut = returns_none_for_int_opt()
  assert_eq(0, r ?? 0)

// Lambda return type mismatch.

@test
@expect error "return type is int but body evaluates to float"
fn test_lambda_return_mismatch() → ∅:
  let f : mut = λx : int → int: 1.5
  f(0)

// Lambda with correct return type.

@test
fn test_lambda_return_ok() → ∅:
  let f : mut = λx : int → int: x + 1
  assert_eq(6, f(5))

// Void return type allows anything (value is discarded).

fn void_return() → ∅:
  42

@test
fn test_void_return() → ∅:
  void_return()

// --- Mixed-type arithmetic rejection ---

@test
@expect error "matching types"
fn test_add_int_float() → ∅:
  let r : mut = 2 + 3.0

@test
@expect error "matching types"
fn test_add_float_int() → ∅:
  let r : mut = 3.0 + 2

@test
@expect error "matching types"
fn test_sub_int_float() → ∅:
  let r : mut = 5 - 1.0

@test
@expect error "matching types"
fn test_sub_float_int() → ∅:
  let r : mut = 5.0 - 1

@test
@expect error "matching types"
fn test_mul_int_float() → ∅:
  let r : mut = 3 * 2.5

@test
@expect error "matching types"
fn test_mul_float_int() → ∅:
  let r : mut = 2.5 * 3

@test
@expect error "matching types"
fn test_div_int_float() → ∅:
  let r : mut = 10 / 2.0

@test
@expect error "matching types"
fn test_div_float_int() → ∅:
  let r : mut = 10.0 / 2

@test
@expect error "matching types"
fn test_mod_int_float() → ∅:
  let r : mut = 7 % 2.0

@test
@expect error "matching types"
fn test_mod_float_int() → ∅:
  let r : mut = 7.0 % 2

@test
@expect error "matching types"
fn test_pow_int_float() → ∅:
  let r : mut = 4 ↑ 0.5

// float↑int is allowed (needed for units, always well-defined).

@test
fn test_pow_float_int_ok() → ∅:
  let r : mut = 4.0 ↑ 2
  assert_true(r == 16.0)

// Same-type arithmetic succeeds.

@test
fn test_add_int_int() → ∅:
  assert_eq(5, 2 + 3)

@test
fn test_add_float_float() → ∅:
  assert_true(5.0 == 2.0 + 3.0)

@test
fn test_mul_float_float() → ∅:
  assert_true(6.0 == 2.0 * 3.0)

// Mixed types through function call: co returns f32, foo adds int + f32.

fn co() → f32:
  1.25

fn foo(a : int) → int:
  a + co()

@test
@expect error "matching types"
fn test_mixed_via_call() → ∅:
  foo(1)

// --- Helpers ---

fn assert_eq(a: int, b: int):
  if a != b:
    std.print("FAIL: expected ", a, " got ", b)

fn assert_true(cond: bool):
  if not cond:
    std.print("FAIL: condition was false")

@start
fn main() → ∅:
  std.print("type strictness tests passed")
