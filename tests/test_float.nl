// Floating-point type tests: f16, f32, f64, bfloat, float
// Tests literals, arithmetic, comparisons, type coercion, and formatting.

fn assert_true cond:bool, msg:str:
  if not cond:
    std.print(msg)

fn test_float_literals:
  // Untyped float literal (inferred as "float")
  static_assert(3.14 > 3.0)
  static_assert(3.14 < 4.0)

  // Typed float literals with suffix
  static_assert(1.0f32 == 1.0f32)

  // Exponent notation
  static_assert(1e3 == 1000.0)
  static_assert(1.5e2 == 150.0)

  // Negative exponent
  static_assert(2.5e-1 == 0.25)

  // Integer with float suffix becomes float
  static_assert(42f32 == 42.0f32)

fn test_float_arithmetic:
  // Addition
  static_assert(3.0 + 2.0 == 5.0)

  // Subtraction
  static_assert(3.0 - 2.0 == 1.0)

  // Multiplication
  static_assert(3.0 * 2.0 == 6.0)

  // Division
  var quot := 3.0 / 2.0
  assert_true(quot == 1.5, "3.0 / 2.0 should be 1.5")

  // Modulus
  var rem := 7.0 % 3.0
  assert_true(rem == 1.0, "7.0 % 3.0 should be 1.0")

  // Negation
  static_assert(⁻3.0 == ⁻3.0)
  static_assert(⁻3.0 + 3.0 == 0.0)

fn test_mixed_int_float:
  // Int + float promotes to float
  static_assert(2 + 3.0 == 5.0)

  // Float + int promotes to float
  static_assert(3.0 + 2 == 5.0)

  // Int * float
  static_assert(3 * 2.5 == 7.5)

  // Float / int
  var d := 10.0 / 4
  assert_true(d == 2.5, "10.0 / 4 should be 2.5")

fn test_float_comparisons:
  static_assert(1.0 < 2.0)
  static_assert(2.0 > 1.0)
  static_assert(1.0 <= 1.0)
  static_assert(1.0 >= 1.0)
  static_assert(1.0 <= 2.0)
  static_assert(2.0 >= 1.0)
  static_assert(1.0 != 2.0)
  static_assert(1.0 == 1.0)

  // Mixed int-float comparison
  static_assert(1.0 == 1)
  static_assert(2 > 1.5)
  static_assert(1.5 < 2)

fn test_typed_float_widths:
  // All should be equal in value
  static_assert(1.5f16 == 1.5f32)
  static_assert(1.5f32 == 1.5f64)

  // Verify type names
  static_assert_eq(@typeof(1.0f16), @typeof(0.0f16))
  static_assert_eq(@typeof(1.0f32), @typeof(0.0f32))
  static_assert_eq(@typeof(1.0f64), @typeof(0.0f64))
  static_assert_eq(@typeof(1.0), @typeof(0.0))

fn add_floats x:f64, y:f64 -> f64:
  x + y

fn as_f32 x:f32 -> f32:
  x

fn test_float_coercion_in_functions:
  // Test int-to-float parameter coercion
  var r := add_floats(3, 4)
  assert_true(r == 7.0, "add_floats(3, 4) should be 7.0")

  // Test float-to-float coercion (narrowing)
  var s := as_f32(3.14)
  // f32 precision: 3.14 becomes approximately 3.140000104904175
  assert_true(s > 3.13, "as_f32(3.14) should be > 3.13")
  assert_true(s < 3.15, "as_f32(3.14) should be < 3.15")

fn test_float_in_conditionals:
  var x := 0.0
  if x:
    assert_true(false, "0.0 should be falsy")
  var y := 1.5
  if not y:
    assert_true(false, "1.5 should be truthy")

fn test_float_format:
  var alloc := std.heap.allocator()
  var s := std.format(alloc, "value: {}", 3.14)
  assert_true(s == "value: 3.14", "format float failed")

  // Fixed-point format specifier
  var s2 := std.format(alloc, "{:.2f}", 3.14)
  assert_true(s2 == "3.14", "format .2f failed")

  // Scientific notation
  var s3 := std.format(alloc, "{:.2e}", 1500.0)
  assert_true(s3 == "1.50e+03", "format .2e failed")

fn test_hex_float_literal:
  // Hex float: 0x1.8p1 = 1.5 * 2^1 = 3.0
  var a := 0x1.8p1
  assert_true(a == 3.0, "0x1.8p1 should be 3.0")

  // 0x1p0 = 1.0
  var b := 0x1p0
  assert_true(b == 1.0, "0x1p0 should be 1.0")

  // 0x1p-1 = 0.5
  var c := 0x1p-1
  assert_true(c == 0.5, "0x1p-1 should be 0.5")

fn reject_float x:i32 -> i32:
  x

fn test_float_type_rejection:
  // Float should not be accepted where int is expected
  @expect error "expected i32"
  reject_float(3.14)

@start
fn main:
  test_float_literals()
  test_float_arithmetic()
  test_mixed_int_float()
  test_float_comparisons()
  test_typed_float_widths()
  test_float_coercion_in_functions()
  test_float_in_conditionals()
  test_float_format()
  test_hex_float_literal()
  test_float_type_rejection()
  std.print("float tests passed")
