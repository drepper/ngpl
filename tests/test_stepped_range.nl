/* Tests for stepped range syntax: start…step…end */

@test
fn test_step_ascending → ∅:
    var sum := 0
    foreach i :=1…2…9:
        sum ← sum + i
    assert_eq(sum, 25) /* 1 + 3 + 5 + 7 + 9 */

@test
fn test_step_even → ∅:
    var sum := 0
    foreach i :=0…2…10:
        sum ← sum + i
    assert_eq(sum, 30) /* 0 + 2 + 4 + 6 + 8 + 10 */

@test
fn test_step_descending → ∅:
    var sum := 0
    foreach i :=10…⁻2…0:
        sum ← sum + i
    assert_eq(sum, 30) /* 10 + 8 + 6 + 4 + 2 + 0 */

@test
fn test_step_no_overshoot → ∅:
    var sum := 0
    foreach i :=0…3…10:
        sum ← sum + i
    assert_eq(sum, 18) /* 0 + 3 + 6 + 9 */

@test
fn test_step_single_element → ∅:
    var count := 0
    foreach i :=5…10…5:
        count ← count + 1
    assert_eq(count, 1) /* only 5 */

@test
fn test_step_large → ∅:
    var sum := 0
    foreach i :=0…64…191:
        sum ← sum + i
    assert_eq(sum, 192) /* 0 + 64 + 128 */

@start
fn main → ∅:
    std.print("stepped range tests passed")
