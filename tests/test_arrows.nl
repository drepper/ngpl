// test_arrows.nl — verify ASCII arrow forms <- and -> work as aliases

// -> works for function return type (ASCII form of →)
fn add_ascii a: i32, b: i32 -> i32:
  a + b

@test
fn test_ascii_arrow_return:
  assert_eq(7, add_ascii(3, 4))

// <- works for assignment (ASCII form of ←)
@test
fn test_ascii_arrow_assign:
  var x := 10
  x <- 20
  assert_eq(20, x)

// <- in array element assignment
@test
fn test_ascii_arrow_array_assign:
  var a := [1, 2, 3]
  a[1] <- 99
  assert_eq(99, a[1])

// -> in lambda return type (ASCII form)
@test
fn test_ascii_arrow_lambda:
  var f := λx : int -> int: x * 3
  assert_eq(15, f(5))

// Mix: ASCII -> for return, Unicode ← for assignment
@test
fn test_mixed_arrows:
  var x := 0
  x ← add_ascii(1, 2)
  assert_eq(3, x)

// Mix: Unicode → for return type (in a helper), ASCII <- for assignment
fn double_unicode x: i32 → i32:
  x * 2

@test
fn test_unicode_arrow_return:
  var x := double_unicode(7)
  assert_eq(14, x)

// Unicode → in lambda
@test
fn test_unicode_arrow_lambda:
  var f := λx : int → int: x + 10
  assert_eq(42, f(32))

@start
fn main:
  0
