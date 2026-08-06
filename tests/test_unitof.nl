// Tests for @unitof intrinsic and standalone ¤unit references.

fn assert_true cond:bool, msg:str:
  if not cond:
    std.print("FAIL: ", msg)

// --- @unitof returns the unit of a unit-bearing value ---

@test
fn test_unitof_meter:
  var a ¤meter := 5
  assert_true(@unitof(a) == ¤meter, "unitof meter")

@test
fn test_unitof_second:
  var t ¤second := 10
  assert_true(@unitof(t) == ¤second, "unitof second")

@test
fn test_unitof_kilogram:
  var m ¤kilogram := 3
  assert_true(@unitof(m) == ¤kilogram, "unitof kilogram")

// --- @unitof on dimensionless value ---

@test
fn test_unitof_dimensionless:
  var x := 42
  assert_true(@unitof(x) != ¤meter, "dimensionless != meter")

// --- @unitof equality of same unit ---

@test
fn test_unitof_same_unit:
  var a ¤meter := 5
  var b ¤meter := 10
  assert_true(@unitof(a) == @unitof(b), "same unit vars equal")

// --- @unitof inequality of different units ---

@test
fn test_unitof_different_units:
  var a ¤meter := 5
  var b ¤second := 3
  assert_true(@unitof(a) != @unitof(b), "meter != second")

// --- @unitof on sizeof result ---

@test
fn test_unitof_sizeof:
  var arr := [1, 2, 3]
  var sz := arr.sizeof
  assert_true(@unitof(sz) == ¤ptrdiff, "sizeof has unit ptrdiff")

@test
fn test_unitof_sizeof_bytes:
  var buf: u8[4] = [1, 2, 3, 4]
  var sz := buf.sizeof
  assert_true(@unitof(sz) == ¤byte, "sizeof u8[] has unit byte")

// --- @unitof on derived unit ---

@test
fn test_unitof_derived:
  var d ¤meter := 100
  var t ¤second := 10
  var speed := d / t
  assert_true(@unitof(speed) == ¤meter/second, "speed has unit m/s")

// --- @unitof with kilometer (same dimension as meter but different unit) ---

@test
fn test_unitof_kilometer:
  var d ¤kilometer := 5
  assert_true(@unitof(d) == ¤kilometer, "unitof kilometer")
  assert_true(@unitof(d) != ¤meter, "kilometer != meter")

// --- static_assert_eq with @unitof ---

@test
fn test_static_assert_unitof:
  var a ¤meter := 5
  static_assert_eq(@unitof(a), ¤meter)

// --- dimensionless comparison ---

@test
fn test_unitof_dimensionless_eq:
  var x := 42
  var y := 99
  assert_true(@unitof(x) == @unitof(y), "both dimensionless")

@start
fn main:
  test_unitof_meter()
  test_unitof_second()
  test_unitof_kilogram()
  test_unitof_dimensionless()
  test_unitof_same_unit()
  test_unitof_different_units()
  test_unitof_sizeof()
  test_unitof_sizeof_bytes()
  test_unitof_derived()
  test_unitof_kilometer()
  test_static_assert_unitof()
  test_unitof_dimensionless_eq()
  std.print("unitof tests passed")
