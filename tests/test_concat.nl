// test_concat.nl -- tests for ⧺ (array concatenation at outermost dimension)

// --- Basic concatenation ---

@test
fn test_concat_two_arrays():
    let a : mut = [1, 2, 3]
    let b : mut = [4, 5]
    let c : mut = a ⧺ b
    assert_eq(c.sizeof, 5)
    assert_eq(c[0], 1)
    assert_eq(c[4], 5)

// --- Concatenate with empty array ---

@test
fn test_concat_empty_left():
    let a : mut = 0 ⍴ [0]
    let b : mut = [1, 2]
    let c : mut = a ⧺ b
    assert_eq(c.sizeof, 2)
    assert_eq(c[0], 1)

@test
fn test_concat_empty_right():
    let a : mut = [1, 2]
    let b : mut = 0 ⍴ [0]
    let c : mut = a ⧺ b
    assert_eq(c.sizeof, 2)
    assert_eq(c[1], 2)

// --- Chained concatenation ---

@test
fn test_concat_chain():
    let r : mut = [1] ⧺ [2] ⧺ [3]
    assert_eq(r.sizeof, 3)
    assert_eq(r[0], 1)
    assert_eq(r[1], 2)
    assert_eq(r[2], 3)

// --- Concatenation with reshape ---

@test
fn test_concat_with_reshape():
    let a : mut = [10, 20]
    let b : mut = a ⧺ 3 ⍴ [0]
    assert_eq(b.sizeof, 5)
    assert_eq(b[0], 10)
    assert_eq(b[1], 20)
    assert_eq(b[2], 0)
    assert_eq(b[3], 0)
    assert_eq(b[4], 0)

// --- Type errors ---

@test
@expect error "left operand must be an array"
fn test_concat_left_not_array():
    42 ⧺ [1]

@test
@expect error "right operand must be an array"
fn test_concat_right_not_array():
    [1] ⧺ 42

// --- Preserves element type ---

@test
fn test_concat_typed_arrays():
    let a : mut u32[2] = 0
    let b : mut u32[3] = 0
    a[0] ← 100
    a[1] ← 200
    b[0] ← 300
    let c : mut = a ⧺ b
    assert_eq(c.sizeof, 5)
    assert_eq(c[0], 100)
    assert_eq(c[2], 300)

// --- Concatenation in expression context ---

@test
fn test_concat_in_assignment():
    let x : mut = [1, 2]
    x ← x ⧺ [3, 4]
    assert_eq(x.sizeof, 4)
    assert_eq(x[3], 4)

@start
fn main():
    0
