// test_view_assign.nl -- reshape-as-view with multi-dimensional slice assignment

@test
fn test_reshape_view_write() → ∅:
  let a: mut i32[] = 16 ⍴ 0
  ((4, 4) ⍴ a)[1…2,1…2] = (2, 2) ⍴ 1
  let exp: mut i32[16] = [0,0,0,0,0,1,1,0,0,1,1,0,0,0,0,0]
  assert_eq(a, exp)

@test
fn test_reshape_view_read() → ∅:
  let a: mut i32[] = 1…16
  let m : mut = (4, 4) ⍴ a
  assert_eq(m[0, 0], 1)
  assert_eq(m[1, 1], 6)
  assert_eq(m[3, 3], 16)

@test
fn test_reshape_view_propagates() → ∅:
  let a: mut i32[] = 4 ⍴ 0
  let m : mut = (2, 2) ⍴ a
  m[0, 1] = 42
  assert_eq(a[1], 42)

// --- call-by-reference: reshape inside function modifies caller's array ---

fn reshape_by_ref(arr : &i32[]) → ∅:
  let m : mut = (2, 2) ⍴ arr
  m[0, 1] = 42

@test
fn test_reshape_ref_modifies_caller() → ∅:
  let a : mut i32[] = 4 ⍴ 0
  reshape_by_ref(&a)
  assert_eq(a[1], 42)

// --- call-by-value: reshape inside function does NOT modify caller's array ---

fn reshape_by_val(arr : i32[]) → ∅:
  let m : mut = (2, 2) ⍴ arr
  m[0, 1] = 99

@test
fn test_reshape_val_no_modify() → ∅:
  let a : mut i32[] = 4 ⍴ 0
  reshape_by_val(a)
  assert_eq(a[1], 0)

// --- call-by-reference: direct element assignment modifies caller ----------

fn set_element_ref(arr : &i32[], idx, val : i32) → ∅:
  arr[idx] = val

@test
fn test_element_ref_modifies_caller() → ∅:
  let a : mut i32[] = [10, 20, 30]
  set_element_ref(&a, 1, 77)
  assert_eq(a[1], 77)

// --- call-by-value: direct element assignment does NOT modify caller --------

fn set_element_val(arr : i32[], idx, val : i32) → ∅:
  arr[idx] = val

@test
fn test_element_val_no_modify() → ∅:
  let a : mut i32[] = [10, 20, 30]
  set_element_val(a, 1, 77)
  assert_eq(a[1], 20)

@start
fn main() → ∅:
  std.print("view assign tests passed")
