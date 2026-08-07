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

@start
fn main() → ∅:
  std.print("view assign tests passed")
