/* Tests for fold operators: left fold ⌿ and right fold ⍀. */

/* Left fold: sum without init (first element is accumulator). */
@test
fn test_left_fold_sum → ∅:
    var result := (λa : int, b : int → int: a + b) ⌿ [1, 2, 3, 4, 5]
    assert_eq(result, 15)

/* Left fold: product without init. */
@test
fn test_left_fold_product → ∅:
    var result := (λa : int, b : int → int: a * b) ⌿ [1, 2, 3, 4, 5]
    assert_eq(result, 120)

/* Left fold: with explicit init via 2-tuple. */
@test
fn test_left_fold_with_init → ∅:
    var result := (λa : int, b : int → int: a + b) ⌿ ([1, 2, 3, 4, 5], 100)
    assert_eq(result, 115)

/* Right fold: difference (right-associative) without init. */
@test
fn test_right_fold_subtract → ∅:
    /* ⍀ [1,2,3] = f(1, f(2, 3)) = 1 - (2 - 3) = 1 - (-1) = 2 */
    var result := (λa : int, b : int → int: a - b) ⍀ [1, 2, 3]
    assert_eq(result, 2)

/* Right fold: with init. */
@test
fn test_right_fold_with_init → ∅:
    /* f(1, f(2, f(3, 0))) = 1 - (2 - (3 - 0)) = 2 */
    var result := (λa : int, b : int → int: a - b) ⍀ ([1, 2, 3], 0)
    assert_eq(result, 2)

/* Left fold: string concatenation without init. */
@test
fn test_left_fold_concat → ∅:
    var result := (λacc : str, s : str → str: acc + s) ⌿ ["a", "b", "c"]
    assert_eq(result, "abc")

/* Right fold: string concatenation without init. */
@test
fn test_right_fold_concat → ∅:
    var result := (λs : str, acc : str → str: s + acc) ⍀ ["a", "b", "c"]
    assert_eq(result, "abc")

/* Left fold with init over empty array returns init. */
@test
fn test_left_fold_empty_with_init → ∅:
    var result := (λa : int, b : int → int: a + b) ⌿ ([], 42)
    assert_eq(result, 42)

/* Right fold with init over empty array returns init. */
@test
fn test_right_fold_empty_with_init → ∅:
    var result := (λa : int, b : int → int: a + b) ⍀ ([], 42)
    assert_eq(result, 42)

/* Left fold over a range without init. */
@test
fn test_left_fold_range → ∅:
    var result := (λa : int, b : int → int: a + b) ⌿ 1…5
    assert_eq(result, 15)

/* Left fold: bit packing with init (used in sha256). */
@test
fn test_left_fold_bit_pack → ∅:
    var result := (λacc : int, h : int → int: (acc « 8) | h) ⌿ ([0xAB, 0xCD, 0xEF], 0)
    assert_eq(result, 0xABCDEF)

/* Left fold with a named function, no init. */
fn add x : int, y : int → int:
    x + y

@test
fn test_left_fold_named_fn → ∅:
    var result := add ⌿ [10, 20, 30]
    assert_eq(result, 60)

/* Left fold with a named function, with init. */
@test
fn test_left_fold_named_fn_init → ∅:
    var result := add ⌿ ([10, 20, 30], 100)
    assert_eq(result, 160)

/* Left fold: single element array, no init. */
@test
fn test_left_fold_single → ∅:
    var result := (λa : int, b : int → int: a + b) ⌿ [7]
    assert_eq(result, 7)

/* Right fold: accumulator from right. */
@test
fn test_right_fold_build → ∅:
    var result := (λa : int, b : int → int: a + b * 2) ⍀ ([1, 2, 3], 0)
    /* f(3, 0) = 3, f(2, 3) = 2+6=8, f(1, 8) = 1+16=17 */
    assert_eq(result, 17)

/* Error: fold without init on empty container. */
@test
@expect error "empty container requires an initial value"
fn test_fold_empty_no_init → ∅:
    var result := add ⌿ []
    result

/* Error: fold with non-iterable. */
@test
@expect error "fold requires array or range"
fn test_fold_non_iterable → ∅:
    var result := add ⌿ 42
    result

@start
fn main → ∅:
    std.print("fold tests passed")
