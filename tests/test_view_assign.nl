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

// &mut: the view shares the caller's storage and is written through,
// so the parameter has to be lent for writing, not just for reading.
fn reshape_by_ref(arr : &mut i32[]) → ∅:
  let m : mut = (2, 2) ⍴ arr
  m[0, 1] = 42

@test
fn test_reshape_ref_modifies_caller() → ∅:
  let a : mut i32[] = 4 ⍴ 0
  reshape_by_ref(&a)
  assert_eq(a[1], 42)

// --- call-by-value: reshape inside function does NOT modify caller's array ---

// mut, because the view is written through.  The parameter is this
// function's own copy, so the caller is still unaffected.
fn reshape_by_val(arr : mut i32[]) → ∅:
  let m : mut = (2, 2) ⍴ arr
  m[0, 1] = 99

@test
fn test_reshape_val_no_modify() → ∅:
  let a : mut i32[] = 4 ⍴ 0
  reshape_by_val(a)
  assert_eq(a[1], 0)

// --- call-by-reference: direct element assignment modifies caller ----------

// &mut, not &: a shared borrow says where the value lives, not that
// the callee may change it.  This one does change it, and the caller
// sees the change.
fn set_element_ref(arr : &mut i32[], idx, val : i32) → ∅:
  arr[idx] = val

@test
fn test_element_ref_modifies_caller() → ∅:
  let a : mut i32[] = [10, 20, 30]
  set_element_ref(&a, 1, 77)
  assert_eq(a[1], 77)

// --- call-by-value: direct element assignment does NOT modify caller --------

// mut, because writing an element is writing to the binding, and a
// parameter is immutable by default.  The copy is what is written, so
// the caller is still unaffected -- which is what this tests.
fn set_element_val(arr : mut i32[], idx, val : i32) → ∅:
  arr[idx] = val

@test
fn test_element_val_no_modify() → ∅:
  let a : mut i32[] = [10, 20, 30]
  set_element_val(a, 1, 77)
  assert_eq(a[1], 20)

// --- dynamic param accepts fixed-size array --------------------------------

fn sum_dynamic(arr : i32[]) → i32:
  let total : mut = 0
  foreach i := 0…(arr.sizeof - 1):
    total ← total + arr[i]
  total

@test
fn test_dynamic_accepts_fixed() → ∅:
  let a : mut i32[3] = [10, 20, 30]
  assert_eq(sum_dynamic(a), 60)

// --- fixed-size param accepts dynamic array of exact size ------------------

fn sum_fixed(arr : i32[3]) → i32:
  arr[0] + arr[1] + arr[2]

@test
fn test_fixed_accepts_dynamic_exact() → ∅:
  let a : mut i32[] = [10, 20, 30]
  assert_eq(sum_fixed(a), 60)

// --- fixed-size param also accepts fixed-size of same length ---------------

@test
fn test_fixed_accepts_fixed_same() → ∅:
  let a : mut i32[3] = [10, 20, 30]
  assert_eq(sum_fixed(a), 60)

@start
fn main() → ∅:
  std.print("view assign tests passed")
