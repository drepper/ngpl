// Tests for sizeof returning unit-bearing values and dimensionless arithmetic.

fn assert_eq_int(a:i64, b:i64, msg:str):
  if a != b:
    std.print("FAIL: ", msg, " (got ", a, " expected ", b, ")")

fn assert_true(cond:bool, msg:str):
  if not cond:
    std.print("FAIL: ", msg)

// --- sizeof returns ptrdiff unit ---

@test
fn test_sizeof_array_ptrdiff():
  let arr := [10, 20, 30]
  let sz := arr.sizeof
  assert_eq_int(sz, 3, "array sizeof is 3")

@test
fn test_sizeof_string_ptrdiff():
  let s := "hello"
  let sz := s.sizeof
  assert_eq_int(sz, 5, "string sizeof is 5")

// --- sizeof byte[] returns byte unit ---

@test
fn test_sizeof_byte_array():
  let buf: u8[4] = [1, 2, 3, 4]
  let sz := buf.sizeof
  assert_eq_int(sz, 4, "byte array sizeof is 4")

// --- dimensionless + unit-bearing: addition ---

@test
fn test_add_unit_plus_dimensionless():
  let a ¤meter := 10
  let b := a + 3
  assert_eq_int(b, 13, "10m + 3")

@test
fn test_add_dimensionless_plus_unit():
  let a ¤meter := 10
  let b := 5 + a
  assert_eq_int(b, 15, "5 + 10m")

// --- dimensionless + unit-bearing: subtraction ---

@test
fn test_sub_unit_minus_dimensionless():
  let a ¤meter := 10
  let b := a - 3
  assert_eq_int(b, 7, "10m - 3")

@test
fn test_sub_dimensionless_minus_unit():
  let a ¤meter := 10
  let b := 20 - a
  assert_eq_int(b, 10, "20 - 10m")

// --- dimensionless * unit-bearing: multiplication preserves unit ---

@test
fn test_mul_unit_times_dimensionless():
  let a ¤meter := 5
  let b := a × 3
  assert_eq_int(b, 15, "5m × 3 = 15m")

@test
fn test_mul_dimensionless_times_unit():
  let a ¤meter := 5
  let b := 3 × a
  assert_eq_int(b, 15, "3 × 5m = 15m")

// --- dimensionless / unit-bearing ---

@test
fn test_div_unit_by_dimensionless():
  let a ¤meter := 12
  let b := a / 3
  assert_eq_int(b, 4, "12m / 3 = 4m")

// --- dimensionless % unit-bearing ---

@test
fn test_mod_unit_by_dimensionless():
  let a ¤meter := 10
  let b := a % 3
  assert_eq_int(b, 1, "10m % 3 = 1m")

@test
fn test_mod_dimensionless_by_unit():
  let a ¤meter := 3
  let b := 10 % a
  assert_eq_int(b, 1, "10 % 3m = 1m")

// --- comparison with dimensionless ---

@test
fn test_cmp_unit_with_dimensionless():
  let a ¤meter := 5
  assert_true(a > 3, "5m > 3")
  assert_true(2 < a, "2 < 5m")
  assert_true(a == 5, "5m == 5")

// --- sizeof result used in arithmetic ---

@test
fn test_sizeof_in_arithmetic():
  let arr := [10, 20, 30, 40, 50]
  let sz := arr.sizeof
  let doubled := sz × 2
  assert_eq_int(doubled, 10, "sizeof×2")
  let plus_one := sz + 1
  assert_eq_int(plus_one, 6, "sizeof+1")

// --- @sizeof on compile-time constant ---

@test
fn test_at_sizeof_ptrdiff():
  let sz := @sizeof([1, 2, 3])
  assert_eq_int(sz, 3, "@sizeof literal is 3")

@start
fn main():
  test_sizeof_array_ptrdiff()
  test_sizeof_string_ptrdiff()
  test_sizeof_byte_array()
  test_add_unit_plus_dimensionless()
  test_add_dimensionless_plus_unit()
  test_sub_unit_minus_dimensionless()
  test_sub_dimensionless_minus_unit()
  test_mul_unit_times_dimensionless()
  test_mul_dimensionless_times_unit()
  test_div_unit_by_dimensionless()
  test_mod_unit_by_dimensionless()
  test_mod_dimensionless_by_unit()
  test_cmp_unit_with_dimensionless()
  test_sizeof_in_arithmetic()
  test_at_sizeof_ptrdiff()
  std.print("sizeof_units tests passed")
