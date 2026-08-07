// Tests for enumerate: produces (index, value) tuples from a container.

// Basic enumerate over an array.
@test
fn test_enumerate_basic() → ∅:
    let indices : mut = 0
    let values : mut = 0
    foreach pair := enumerate([10, 20, 30]):
        indices ← indices + pair[0]
        values ← values + pair[1]
    assert_eq(indices, 3)   // 0 + 1 + 2
    assert_eq(values, 60)   // 10 + 20 + 30

// Enumerate with two variables (index, value destructured).
@test
fn test_enumerate_two_vars() → ∅:
    let sum : mut = 0
    foreach i, v := enumerate([5, 4, 3, 2, 1]):
        sum ← sum + i * v
    // 0*5 + 1*4 + 2*3 + 3*2 + 4*1 = 0+4+6+6+4 = 20
    assert_eq(sum, 20)

// Enumerate over an empty array.
@test
fn test_enumerate_empty() → ∅:
    let count : mut = 0
    foreach pair := enumerate([]):
        count ← count + 1
    assert_eq(count, 0)

// Enumerate over a single-element array.
@test
fn test_enumerate_single() → ∅:
    let idx : mut = ⁻1
    let val : mut = ⁻1
    foreach i, v := enumerate([42]):
        idx ← i
        val ← v
    assert_eq(idx, 0)
    assert_eq(val, 42)

// Enumerate with range value.
@test
fn test_enumerate_range() → ∅:
    let sum_idx : mut = 0
    let sum_val : mut = 0
    foreach pair := enumerate(10…14):
        sum_idx ← sum_idx + pair[0]
        sum_val ← sum_val + pair[1]
    assert_eq(sum_idx, 10)   // 0+1+2+3+4
    assert_eq(sum_val, 60)   // 10+11+12+13+14

// Enumerate used with generate.
fn square(x : int) → int:
    x * x

@test
fn test_enumerate_generated() → ∅:
    let arr : mut = generate(square, 1…4)
    let total : mut = 0
    foreach i, v := enumerate(arr):
        total ← total + i + v
    // values: 1,4,9,16; indices: 0,1,2,3
    // total = (0+1) + (1+4) + (2+9) + (3+16) = 36
    assert_eq(total, 36)

// Error: enumerate outside foreach.
@test
@expect error "enumerate can only be used inside foreach"
fn test_enumerate_outside_foreach() → ∅:
    let x : mut = enumerate([1, 2, 3])

@start
fn main() → ∅:
    std.print("enumerate tests passed")
