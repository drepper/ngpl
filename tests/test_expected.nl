/* Tests for expected (result) types: T?E syntax, division returning
 * expected values, ? propagation, ?? recovery, and comparison with
 * optional (T?) types.
 */

/* ---- postfix optional syntax (T?) ---------------------------------------- */

fn opt_double(x : int?) → int?:
    let v : mut = x?
    v * 2

@test
fn test_optional_postfix_some() → ∅:
    let r : mut = opt_double(some(5))
    assert_eq(r ?? ⁻1, 10)

@test
fn test_optional_postfix_none() → ∅:
    let r : mut = opt_double(∅)
    assert_eq(r ?? ⁻1, ⁻1)

/* ---- division returns expected value ------------------------------------- */

@test
fn test_div_success_unwrap() → ∅:
    let x : mut = 10 / 3
    let v : mut = x ?? ⁻1
    assert_eq(v, 3)

@test
fn test_div_zero_recovery() → ∅:
    let x : mut = 10 / 0
    let v : mut = x ?? ⁻1
    assert_eq(v, ⁻1)

@test
fn test_mod_success_unwrap() → ∅:
    let x : mut = 10 % 3
    let v : mut = x ?? ⁻1
    assert_eq(v, 1)

@test
fn test_mod_zero_recovery() → ∅:
    let x : mut = 10 % 0
    let v : mut = x ?? ⁻1
    assert_eq(v, ⁻1)

/* ---- ? propagation for expected values ----------------------------------- */

fn safe_div(a : int, b : int) → int?std.errors:
    (a / b)?

@test
fn test_expected_propagate_ok() → ∅:
    let r : mut = safe_div(10, 2)
    assert_eq(r ?? ⁻1, 5)

@test
fn test_expected_propagate_err() → ∅:
    let r : mut = safe_div(10, 0)
    assert_eq(r ?? ⁻1, ⁻1)

/* ---- chained division with ?? -------------------------------------------- */

@test
fn test_div_chain_recovery() → ∅:
    let a : mut = (100 / 10) ?? 0
    let b : mut = (a / 2) ?? 0
    assert_eq(b, 5)

@test
fn test_div_chain_zero() → ∅:
    let a : mut = (100 / 0) ?? 0
    let b : mut = (a / 2) ?? 0
    assert_eq(b, 0)

/* ---- expected error is std.errors value ---------------------------------- */

fn div_or_err(a : int, b : int) → int?std.errors:
    (a / b)?

@test
fn test_expected_err_is_std_errors() → ∅:
    let r : mut = div_or_err(1, 0)
    let fallback : mut = r ?? ⁻1
    assert_eq(fallback, ⁻1)

/* ---- using unwrapped expected in arithmetic ------------------------------ */

@test
fn test_unwrapped_expected_arithmetic() → ∅:
    let x : mut = (20 / 4) ?? 0
    let y : mut = x + 10
    assert_eq(y, 15)

/* ---- T! abbreviation for T?std.errors ------------------------------------ */

fn bang_div(a : int, b : int) → int!:
    (a / b)?

@test
fn test_bang_return_ok() → ∅:
    let r : mut = bang_div(10, 2)
    assert_eq(r ?? ⁻1, 5)

@test
fn test_bang_return_err() → ∅:
    let r : mut = bang_div(10, 0)
    assert_eq(r ?? ⁻1, ⁻1)

fn bang_param(x : int!) → int:
    x ?? 0

@test
fn test_bang_param_ok() → ∅:
    let v : mut = 10 / 2
    assert_eq(bang_param(v), 5)

@test
fn test_bang_param_err() → ∅:
    let v : mut = 10 / 0
    assert_eq(bang_param(v), 0)

/* ---- error on unwrap of expected error ----------------------------------- */

@expect error "expected error"
fn error_unwrap_expected() → ∅:
    let x : mut = 10 / 0
    let y : mut = x + 1

@start
fn main() → ∅:
    std.print("expected tests passed")
