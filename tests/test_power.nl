// Power operator ↑ tests.

fn assert_true cond:bool, msg:str:
  if not cond:
    std.print("FAIL: ", msg)

fn assert_eq_int a:i64, b:i64, msg:str:
  if a != b:
    std.print("FAIL: ", msg, " (got ", a, " expected ", b, ")")

fn approx_eq a:f64, b:f64, msg:str:
  var diff := a - b
  if diff < 0.0:
    diff ← -diff
  if diff > 0.0001:
    std.print("FAIL: ", msg, " (got ", a, " expected ", b, ")")

// --- Integer exponentiation ---

fn test_int_pow_basic:
  assert_eq_int(2 ↑ 10, 1024, "2↑10")
  assert_eq_int(3 ↑ 4, 81, "3↑4")
  assert_eq_int(5 ↑ 0, 1, "5↑0")
  assert_eq_int(7 ↑ 1, 7, "7↑1")

fn test_int_pow_zero_base:
  assert_eq_int(0 ↑ 5, 0, "0↑5")
  assert_eq_int(0 ↑ 0, 1, "0↑0")

fn test_int_pow_one:
  assert_eq_int(1 ↑ 100, 1, "1↑100")

fn test_int_pow_large:
  assert_eq_int(2 ↑ 20, 1048576, "2↑20")

// --- Negative exponent rejected for integers ---

fn test_int_pow_negative_exp:
  @expect error "non-negative"
  var r := 2 ↑ -1

// --- Float exponentiation ---

fn test_float_pow_basic:
  approx_eq(2.0 ↑ 3.0, 8.0, "2.0↑3.0")
  approx_eq(4.0 ↑ 0.5, 2.0, "4.0↑0.5")
  approx_eq(27.0 ↑ (1.0 / 3.0), 3.0, "27.0↑(1/3)")

fn test_float_pow_negative_exp:
  approx_eq(2.0 ↑ -1.0, 0.5, "2.0↑-1.0")
  approx_eq(4.0 ↑ -0.5, 0.5, "4.0↑-0.5")

fn test_float_pow_zero:
  approx_eq(5.0 ↑ 0.0, 1.0, "5.0↑0.0")

// --- Mixed int base, float exponent ---

fn test_mixed_pow:
  approx_eq(4 ↑ 0.5, 2.0, "4↑0.5")
  approx_eq(8 ↑ (1.0 / 3.0), 2.0, "8↑(1/3)")

// --- Right associativity ---

fn test_right_assoc:
  // 2 ↑ 3 ↑ 2 = 2 ↑ (3 ↑ 2) = 2 ↑ 9 = 512
  assert_eq_int(2 ↑ 3 ↑ 2, 512, "2↑3↑2 right-assoc")

// --- Precedence: ↑ binds tighter than * ---

fn test_precedence_mul:
  // 2 * 3 ↑ 2 = 2 * 9 = 18
  assert_eq_int(2 * 3 ↑ 2, 18, "2*3↑2")

fn test_precedence_neg:
  // -2 ↑ 2 = -(2↑2) = -4 (unary minus binds looser)
  assert_eq_int(-2 ↑ 2, -4, "-2↑2")

// --- Overflow detected ---

fn test_overflow:
  var x: i8 = 2
  @expect error "overflow"
  var r := x ↑ 8

// --- Power with units ---

fn test_unit_pow:
  var d ¤meter := 3.0
  var area := d ↑ 2
  // 3.0 m ^ 2 = 9.0 m^2
  approx_eq(area, 9.0, "3.0m ↑ 2 value")
  std.print(area)

fn test_unit_pow_cube:
  var d ¤meter := 2.0
  var vol := d ↑ 3
  // 2.0 m ^ 3 = 8.0 m^3
  approx_eq(vol, 8.0, "2.0m ↑ 3 value")

fn test_unit_pow_zero:
  var d ¤meter := 5.0
  var r := d ↑ 0
  // m^0 = dimensionless
  approx_eq(r, 1.0, "5.0m ↑ 0 dimensionless")

fn test_unit_exp_rejected:
  var d ¤meter := 5.0
  var e ¤second := 2.0
  @expect error "exponent cannot have a unit"
  var r := d ↑ e

@start
fn main:
  test_int_pow_basic()
  test_int_pow_zero_base()
  test_int_pow_one()
  test_int_pow_large()
  test_int_pow_negative_exp()
  test_float_pow_basic()
  test_float_pow_negative_exp()
  test_float_pow_zero()
  test_mixed_pow()
  test_right_assoc()
  test_precedence_mul()
  test_precedence_neg()
  test_overflow()
  test_unit_pow()
  test_unit_pow_cube()
  test_unit_pow_zero()
  test_unit_exp_rejected()
  std.print("power tests passed")
