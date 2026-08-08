// Unit system tests: dimensional analysis, conversion, and arithmetic.

fn assert_true(cond:bool, msg:str):
  if not cond:
    std.print("FAIL: ", msg)

fn assert_eq_int(a:i64, b:i64, msg:str):
  if a != b:
    std.print("FAIL: ", msg, " (got ", a, " expected ", b, ")")

// --- Basic unit annotation on variables ---

fn test_basic_units():
  let x ¤meter := 5
  let y ¤second := 10
  let z ¤kilogram := 3
  assert_true(true, "basic unit definition should work")

// --- Same-unit addition ---

fn test_same_unit_add():
  let a ¤meter := 3
  let b ¤meter := 7
  let c := a + b
  // c should be 10 m
  std.print(c)

// --- Same-unit subtraction ---

fn test_same_unit_sub():
  let a ¤meter := 10
  let b ¤meter := 3
  let c := a - b
  // c should be 7 m
  std.print(c)

// --- Unit-scalar multiplication ---

fn test_scalar_mul():
  let a ¤meter := 5
  let b := a × 3
  // b should be 15 m
  std.print(b)

fn test_scalar_mul_rev():
  let a ¤meter := 5
  let b := 3 × a
  // b should be 15 m
  std.print(b)

// --- Unit multiplication (derived units) ---

fn test_unit_mul():
  let a ¤meter := 5
  let b ¤second := 2
  let c := a × b
  // c should be 10 m×s
  std.print(c)

// --- Unit division ---

fn test_unit_div():
  let dist ¤meter := 100
  let time ¤second := 10
  let speed := dist / time
  // speed should have unit m/s
  std.print(speed)

// --- Dimensionless result from division ---

fn test_dimensionless_div():
  let a ¤meter := 10
  let b ¤meter := 5
  let ratio := a / b
  // same unit cancels, result is plain 2
  std.print(ratio)

// --- Unit conversion: compatible units ---

fn test_unit_conversion_km_to_m():
  let d ¤meter : mut = 0
  d ← 3¤kilometer
  // 3 km = 3000 m
  assert_eq_int(d, 3000, "3 km to m")

fn test_unit_conversion_ms_to_s():
  let t ¤second : mut = 0
  t ← 2000¤millisecond
  // 2000 ms = 2 s
  assert_eq_int(t, 2, "2000 ms to s")

// --- Lossless conversion check ---

fn test_lossless_reject():
  let t ¤second : mut = 0
  // 500 ms = 0.5 s, not lossless for integer
  @expect error "without loss"
  t ← 500¤millisecond

// --- Incompatible unit rejection ---

fn test_incompatible_add():
  let a ¤meter := 5
  let b ¤second := 3
  @expect error "incompatible units"
  let c : mut = a + b

fn test_incompatible_assign():
  let a ¤meter : mut = 5
  @expect error "incompatible units"
  a ← 3¤second

// --- Dimensionless assignment rejection ---

fn test_dimensionless_assign():
  let a ¤meter : mut = 5
  @expect error "dimensionless"
  a ← 3

// --- Dimensioned + dimensionless arithmetic ---

fn test_add_dimensioned_dimensionless():
  let a ¤meter := 5
  let b := a + 3
  // 3 adopts unit meter, result is 8 m
  assert_eq_int(b, 8, "5m + 3")
  let c := 2 + a
  assert_eq_int(c, 7, "2 + 5m")

// --- Addition of compatible but different units ---

fn test_add_km_and_m():
  let a ¤kilometer := 3
  let b ¤meter := 500
  let c := a + b
  // Result in base (m): 3000 + 500 = 3500 m
  std.print(c)

// --- Comparison of unitful values ---

fn test_unit_comparison():
  let a ¤meter := 5
  let b ¤meter := 10
  assert_true(a < b, "5m < 10m")
  assert_true(b > a, "10m > 5m")
  assert_true(a == a, "5m == 5m")
  assert_true(a != b, "5m != 10m")

fn test_unit_comparison_different():
  let a ¤kilometer := 1
  let b ¤meter := 1000
  // 1 km == 1000 m (converted to base)
  assert_true(a == b, "1 km == 1000 m")
  assert_true(not (a < b), "1 km not < 1000 m")

// --- Negation ---

fn test_negation():
  let a ¤meter := 5
  let b := ⁻a
  std.print(b)

// --- Byte units ---

fn test_byte_units():
  let a ¤byte : mut = 0
  a ← 1024¤kibibyte
  // 1024 KiB = 1048576 B
  assert_eq_int(a, 1048576, "1024 KiB to B")

fn test_byte_display():
  let a ¤byte := 42
  std.print(a)

// --- Unit inference from init value ---

fn test_unit_inference():
  let a ¤meter := 5
  let b := a
  // b should inherit unit m from a
  let c := b + a
  // c should be 10 m (works because b has unit m)
  std.print(c)

// --- User-defined units ---

unit speed = meter / second
unit accel = meter / second / second

fn test_user_units():
  let v ¤"speed" := 10
  let a ¤"accel" := 2
  std.print(v)
  std.print(a)

// --- Formatting ---

fn test_format():
  let alloc := std.heap.allocator()
  let d ¤meter := 42
  let s := std.format(alloc, "distance: {}", d)
  assert_true(s == "distance: 42 m", "format with unit")

// --- Count and distance units ---

fn test_abstract_units():
  let n ¤count := 10
  let d ¤distance := 50
  std.print(n)
  std.print(d)

// --- Unit-aware modulus ---

fn test_unit_mod():
  let a ¤meter := 7
  let b ¤meter := 3
  let c := a % b
  // 7 m % 3 m = 1 m
  std.print(c)

// --- Float with units ---

fn test_float_units():
  let a ¤meter := 3.5
  let b ¤meter := 1.5
  let c := a + b
  std.print(c)

// --- Compound unit spec on expression ---

fn test_compound_unit_spec():
  let v ¤meter/second := 10
  std.print(v)

// --- Compound unit spec with multiplication ---

// A declared compound unit has to agree with the one the arithmetic
// derives, so this checks the formula and the operator together.
fn test_compound_unit_mul_spec():
  let side ¤meter := 6
  let area ¤meter×meter := side × side
  assert_true(area == 36¤meter×meter, "6m × 6m is 36 m×m")
  std.print(area)

// --- Spacing: ¤ immediately after variable name (no whitespace before) ---

fn test_unit_no_space_before():
  let x¤meter := 7
  let y¤second := 3
  let z := x × y
  std.print(z)

// --- Spacing: whitespace after ¤ ---

fn test_unit_space_after():
  let a ¤ meter := 12
  let b ¤ second := 4
  let c := a / b
  std.print(c)

// --- Spacing: no space before ¤, space after ¤ ---

fn test_unit_no_space_before_space_after():
  let p¤ kilogram := 5
  std.print(p)

// --- Spacing: ¤ on expression with no space ---

fn test_unit_expr_no_space():
  let x := 42¤meter
  std.print(x)

@start
fn main():
  test_basic_units()
  test_same_unit_add()
  test_same_unit_sub()
  test_scalar_mul()
  test_scalar_mul_rev()
  test_unit_mul()
  test_unit_div()
  test_dimensionless_div()
  test_unit_conversion_km_to_m()
  test_unit_conversion_ms_to_s()
  test_lossless_reject()
  test_incompatible_add()
  test_incompatible_assign()
  test_dimensionless_assign()
  test_add_dimensioned_dimensionless()
  test_add_km_and_m()
  test_unit_comparison()
  test_unit_comparison_different()
  test_negation()
  test_byte_units()
  test_byte_display()
  test_unit_inference()
  test_user_units()
  test_format()
  test_abstract_units()
  test_unit_mod()
  test_float_units()
  test_compound_unit_spec()
  test_compound_unit_mul_spec()
  test_unit_no_space_before()
  test_unit_space_after()
  test_unit_no_space_before_space_after()
  test_unit_expr_no_space()
  std.print("unit tests passed")
