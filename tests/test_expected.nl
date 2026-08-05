/* Tests for expected (result) types: T?E syntax, division returning
 * expected values, ? propagation, ?? recovery, and comparison with
 * optional (T?) types.
 */

/* ---- postfix optional syntax (T?) ---------------------------------------- */

fn opt_double x : int? -> int?:
    var v := x?
    v * 2

@test
fn test_optional_postfix_some -> ø:
    var r := opt_double(some(5))
    assert_eq(r ?? -1, 10)

@test
fn test_optional_postfix_none -> ø:
    var r := opt_double(ø)
    assert_eq(r ?? -1, -1)

/* ---- division returns expected value ------------------------------------- */

@test
fn test_div_success_unwrap -> ø:
    var x := 10 / 3
    var v := x ?? -1
    assert_eq(v, 3)

@test
fn test_div_zero_recovery -> ø:
    var x := 10 / 0
    var v := x ?? -1
    assert_eq(v, -1)

@test
fn test_mod_success_unwrap -> ø:
    var x := 10 % 3
    var v := x ?? -1
    assert_eq(v, 1)

@test
fn test_mod_zero_recovery -> ø:
    var x := 10 % 0
    var v := x ?? -1
    assert_eq(v, -1)

/* ---- ? propagation for expected values ----------------------------------- */

fn safe_div a : int, b : int -> int?std.errors:
    (a / b)?

@test
fn test_expected_propagate_ok -> ø:
    var r := safe_div(10, 2)
    assert_eq(r ?? -1, 5)

@test
fn test_expected_propagate_err -> ø:
    var r := safe_div(10, 0)
    assert_eq(r ?? -1, -1)

/* ---- chained division with ?? -------------------------------------------- */

@test
fn test_div_chain_recovery -> ø:
    var a := (100 / 10) ?? 0
    var b := (a / 2) ?? 0
    assert_eq(b, 5)

@test
fn test_div_chain_zero -> ø:
    var a := (100 / 0) ?? 0
    var b := (a / 2) ?? 0
    assert_eq(b, 0)

/* ---- expected error is std.errors value ---------------------------------- */

fn div_or_err a : int, b : int -> int?std.errors:
    (a / b)?

@test
fn test_expected_err_is_std_errors -> ø:
    var r := div_or_err(1, 0)
    var fallback := r ?? -1
    assert_eq(fallback, -1)

/* ---- using unwrapped expected in arithmetic ------------------------------ */

@test
fn test_unwrapped_expected_arithmetic -> ø:
    var x := (20 / 4) ?? 0
    var y := x + 10
    assert_eq(y, 15)

/* ---- T! abbreviation for T?std.errors ------------------------------------ */

fn bang_div a : int, b : int -> int!:
    (a / b)?

@test
fn test_bang_return_ok -> ø:
    var r := bang_div(10, 2)
    assert_eq(r ?? -1, 5)

@test
fn test_bang_return_err -> ø:
    var r := bang_div(10, 0)
    assert_eq(r ?? -1, -1)

fn bang_param x : int! -> int:
    x ?? 0

@test
fn test_bang_param_ok -> ø:
    var v := 10 / 2
    assert_eq(bang_param(v), 5)

@test
fn test_bang_param_err -> ø:
    var v := 10 / 0
    assert_eq(bang_param(v), 0)

/* ---- error on unwrap of expected error ----------------------------------- */

@expect error "expected error"
fn error_unwrap_expected -> ø:
    var x := 10 / 0
    var y := x + 1

@start
fn main -> ø:
    std.print("expected tests passed")
