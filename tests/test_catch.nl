// test_catch.nl -- tests for catch statement (scoped error handling)

// --- Helper functions ---

fn safe_get(arr : i32[], idx ¤ptrdiff : i32) → i32?:
    catch:
        arr[idx]

fn safe_get_result(arr : i32[], idx ¤ptrdiff : i32) → i32!:
    catch:
        arr[idx]

fn always_fails() → i32:
    let a : mut = [1]
    a[99]

fn try_call_fail() → i32?:
    catch:
        always_fails()

// --- Direct error caught returns none for optional ---

@test
fn test_catch_oob_optional():
    let result : mut = safe_get([1, 2, 3], 10)
    assert_eq(result, ∅)

// --- No error returns value wrapped in some ---

@test
fn test_catch_success_optional():
    let result : mut = safe_get([1, 2, 3], 1)
    let val : mut = result ?? ⁻1
    assert_eq(val, 2)

// --- Direct error caught returns err for expected ---

@test
fn test_catch_oob_expected():
    let result : mut = safe_get_result([1, 2, 3], 10)
    let val : mut = result ?? ⁻1
    assert_eq(val, ⁻1)

// --- Expected success returns ok value ---

@test
fn test_catch_expected_success():
    let result : mut = safe_get_result([1, 2, 3], 1)
    let val : mut = result ?? ⁻1
    assert_eq(val, 2)

// --- Error from function call is NOT caught (syntactic scope) ---

@test
@expect error "out of range"
fn test_catch_no_cross_call():
    try_call_fail()

// --- Catch requires optional or expected return type ---

@test
@expect error "optional or expected"
fn test_catch_requires_optional():
    catch:
        42

// --- Multiple statements in catch ---

fn multi_stmt(arr : i32[], idx ¤ptrdiff : i32) → i32?:
    catch:
        let x : mut = arr[idx]
        let y : mut = x + 1
        y

@test
fn test_catch_multi_stmt_success():
    let result : mut = multi_stmt([10, 20, 30], 1)
    let val : mut = result ?? ⁻1
    assert_eq(val, 21)

@test
fn test_catch_multi_stmt_fail():
    let result : mut = multi_stmt([10, 20, 30], 5)
    assert_eq(result, ∅)

// --- Negative index caught ---

@test
fn test_catch_negative_index():
    let result : mut = safe_get([1, 2, 3], ⁻1)
    assert_eq(result, ∅)

// --- Catch with code after the block ---

fn catch_then_continue(arr : i32[], idx ¤ptrdiff : i32) → i32?:
    catch:
        arr[idx]

@test
fn test_catch_returns_value_on_success():
    let result : mut = catch_then_continue([5, 6, 7], 0)
    let val : mut = result ?? ⁻1
    assert_eq(val, 5)

@start
fn main():
    0
