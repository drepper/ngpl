/* Test foreach loop: ranges, wrapping, tuples, constants. */

/* Simple range iteration. */
@test
fn test_foreach_range → ∅:
    var sum := 0
    foreach i := 1…10:
        sum ← sum + i
    assert_eq(sum, 55)

/* Descending range. */
@test
fn test_foreach_desc → ∅:
    var result := 0
    foreach i := 5…1:
        result ← result * 10 + i
    assert_eq(result, 54321)

/* Typed loop variable. */
@test
fn test_foreach_typed → ∅:
    var total : u32 = 0
    foreach k : u32 = 0…3:
        total ← total + k
    assert_eq(total, 6)

/* Two variables, two ranges — wrapping shorter range. */
@test
fn test_foreach_wrap → ∅:
    var sum_i := 0
    var sum_j := 0
    foreach i, j := 1…6, 10…12:
        sum_i ← sum_i + i
        sum_j ← sum_j + j
    /* i: 1,2,3,4,5,6                         → 21 */
    /* j: 10,11,12,10,11,12 (wraps around)    → 66 */
    assert_eq(sum_i, 21)
    assert_eq(sum_j, 66)

/* Single variable with multiple ranges → tuple. */
@test
fn test_foreach_tuple → ∅:
    var sum_first := 0
    var sum_second := 0
    foreach pair := 1…3, 10…12:
        sum_first ← sum_first + pair[0]
        sum_second ← sum_second + pair[1]
    assert_eq(sum_first, 6)
    assert_eq(sum_second, 33)

/* Tuple with wrapping: ranges of different lengths. */
@test
fn test_foreach_tuple_wrap → ∅:
    var count := 0
    foreach t := 1…2, 10…13:
        count ← count + 1
    /* Longest range has 4 elements, loop runs 4 times. */
    assert_eq(count, 4)

/* Foreach with brace block. */
@test
fn test_foreach_brace → ∅:
    var sum := 0
    foreach i := 1…5 {
        sum ← sum + i;
    }
    assert_eq(sum, 15)

/* Accumulate array elements using foreach. */
@test
fn test_foreach_array → ∅:
    var data := [10, 20, 30, 40]
    var total := 0
    foreach idx := 0…3:
        total ← total + data[idx]
    assert_eq(total, 100)

@start
fn main → ∅:
    std.print("foreach tests passed")
