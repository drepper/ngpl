/* Tests for fold operators: left fold ⌿ and right fold ⍀. */

/* Left fold: sum of array elements. */
@test
fn test_left_fold_sum → ∅:
    var result := ⌿(λa : int, b : int → int: a + b, [1, 2, 3, 4, 5], 0)
    assert_eq(result, 15)

/* Left fold: product. */
@test
fn test_left_fold_product → ∅:
    var result := ⌿(λa : int, b : int → int: a * b, [1, 2, 3, 4, 5], 1)
    assert_eq(result, 120)

/* Right fold: difference (right-associative). */
@test
fn test_right_fold_subtract → ∅:
    /* ⍀(f, [1,2,3], 0) = f(1, f(2, f(3, 0))) = 1 - (2 - (3 - 0)) = 2 */
    var result := ⍀(λa : int, b : int → int: a - b, [1, 2, 3], 0)
    assert_eq(result, 2)

/* Left fold: string concatenation. */
@test
fn test_left_fold_concat → ∅:
    var result := ⌿(λacc : str, s : str → str: acc + s, ["a", "b", "c"], "")
    assert_eq(result, "abc")

/* Right fold: string concatenation (reversed order). */
@test
fn test_right_fold_concat → ∅:
    var result := ⍀(λs : str, acc : str → str: s + acc, ["a", "b", "c"], "")
    assert_eq(result, "abc")

/* Left fold over empty array returns init. */
@test
fn test_left_fold_empty → ∅:
    var result := ⌿(λa : int, b : int → int: a + b, [] , 42)
    assert_eq(result, 42)

/* Right fold over empty array returns init. */
@test
fn test_right_fold_empty → ∅:
    var result := ⍀(λa : int, b : int → int: a + b, [], 42)
    assert_eq(result, 42)

/* Left fold over a range. */
@test
fn test_left_fold_range → ∅:
    var result := ⌿(λa : int, b : int → int: a + b, 1…5, 0)
    assert_eq(result, 15)

/* Left fold: bit packing (used in sha256). */
@test
fn test_left_fold_bit_pack → ∅:
    var result := ⌿(λacc : int, h : int → int: (acc « 8) | h, [0xAB, 0xCD, 0xEF], 0)
    assert_eq(result, 0xABCDEF)

/* Left fold with a named function. */
fn add x : int, y : int → int:
    x + y

@test
fn test_left_fold_named_fn → ∅:
    var result := ⌿(add, [10, 20, 30], 0)
    assert_eq(result, 60)

/* Left fold: single element array. */
@test
fn test_left_fold_single → ∅:
    var result := ⌿(λa : int, b : int → int: a + b, [7], 100)
    assert_eq(result, 107)

/* Right fold: build list-like structure (cons). */
@test
fn test_right_fold_build → ∅:
    /* f(1, f(2, f(3, 0))) where f(a,b) = a * 10 + b gives 1*(10)+2 then... */
    /* f(3, 0) = 30, f(2, 30) = 50, f(1, 50) = 60  -- no, let's just check arithmetic */
    var result := ⍀(λa : int, b : int → int: a + b * 2, [1, 2, 3], 0)
    /* f(3, 0) = 3, f(2, 3) = 2+6=8, f(1, 8) = 1+16=17 */
    assert_eq(result, 17)

/* Error: fold with non-iterable. */
@test
@expect error "fold requires array or range"
fn test_fold_non_iterable → ∅:
    var result := ⌿(λa : int, b : int → int: a + b, 42, 0)
    result

@start
fn main → ∅:
    std.print("fold tests passed")
