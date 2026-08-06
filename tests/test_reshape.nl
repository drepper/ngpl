// test_reshape.nl — tests for ⍴ (reshape) operator and array bounds checking

// --- ⍴ with scalar creates vector of copies ---

@test
fn test_reshape_scalar:
    var a := 5 ⍴ 0
    assert_eq(a.sizeof, 5)
    assert_eq(a[0], 0)
    assert_eq(a[4], 0)

@test
fn test_reshape_scalar_nonzero:
    var a := 3 ⍴ 42
    assert_eq(a.sizeof, 3)
    assert_eq(a[0], 42)
    assert_eq(a[1], 42)
    assert_eq(a[2], 42)

// --- ⍴ with array cycles elements ---

@test
fn test_reshape_cycle:
    var src := [1, 2, 3]
    var a := 7 ⍴ src
    assert_eq(a.sizeof, 7)
    assert_eq(a[0], 1)
    assert_eq(a[2], 3)
    assert_eq(a[3], 1)
    assert_eq(a[6], 1)

@test
fn test_reshape_extend:
    var src := [10, 20, 30]
    var a := 6 ⍴ src
    assert_eq(a.sizeof, 6)
    assert_eq(a[3], 10)
    assert_eq(a[5], 30)

@test
fn test_reshape_truncate:
    var src := [1, 2, 3, 4, 5]
    var a := 2 ⍴ src
    assert_eq(a.sizeof, 2)
    assert_eq(a[0], 1)
    assert_eq(a[1], 2)

@test
fn test_reshape_identity:
    var src := [5, 6, 7]
    var a := 3 ⍴ src
    assert_eq(a.sizeof, 3)
    assert_eq(a[0], 5)
    assert_eq(a[2], 7)

@test
fn test_reshape_empty:
    var a := 0 ⍴ 42
    assert_eq(a.sizeof, 0)

// --- ⍴ with generate ---

@test
fn test_reshape_with_generate:
    var src := generate(λx : int → int: x * 10, 0…3)
    var a := 8 ⍴ src
    assert_eq(a.sizeof, 8)
    assert_eq(a[0], 0)
    assert_eq(a[1], 10)
    assert_eq(a[4], 0)
    assert_eq(a[7], 30)

// --- ⍴ with range ---

@test
fn test_reshape_range:
    var a := 5 ⍴ (1…3)
    assert_eq(a.sizeof, 5)
    assert_eq(a[0], 1)
    assert_eq(a[2], 3)
    assert_eq(a[3], 1)
    assert_eq(a[4], 2)

// --- ⍴ with variable dimension ---

@test
fn test_reshape_variable_dim:
    var n := 4
    var a := n ⍴ 99
    assert_eq(a.sizeof, 4)
    assert_eq(a[3], 99)

// --- ⍴ creates matrix with tuple shape ---

@test
fn test_reshape_matrix:
    var a := (2, 3) ⍴ 0
    assert_eq(a.sizeof, 2)
    assert_eq(a[0].sizeof, 3)
    assert_eq(a[0][0], 0)
    assert_eq(a[1][2], 0)

@test
fn test_reshape_matrix_data:
    var a := (2, 3) ⍴ [1, 2, 3, 4, 5, 6]
    assert_eq(a[0][0], 1)
    assert_eq(a[0][2], 3)
    assert_eq(a[1][0], 4)
    assert_eq(a[1][2], 6)

@test
fn test_reshape_matrix_cycle:
    var a := (2, 3) ⍴ [1, 2]
    assert_eq(a[0][0], 1)
    assert_eq(a[0][1], 2)
    assert_eq(a[0][2], 1)
    assert_eq(a[1][0], 2)
    assert_eq(a[1][1], 1)
    assert_eq(a[1][2], 2)

// --- Array bounds checking ---

@test
@expect error "out of range"
fn test_array_oob_write:
    var a := [1, 2, 3]
    a[3] ← 4

@test
@expect error "out of range"
fn test_array_oob_read:
    var a := [1, 2, 3]
    var x := a[3]

@test
@expect error "out of range"
fn test_array_negative_write:
    var a := [1, 2, 3]
    a[⁻1] ← 4

@test
@expect error "out of range"
fn test_array_negative_read:
    var a := [1, 2, 3]
    var x := a[⁻1]

// --- ⍴ error conditions ---

@test
@expect error "non-negative"
fn test_reshape_negative_dim:
    var a := ⁻1 ⍴ 0

@test
@expect error "cannot reshape empty"
fn test_reshape_empty_source:
    var a := 5 ⍴ []

@start
fn main:
    0
