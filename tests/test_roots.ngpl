// Root operator tests: √ (square root), ∛ (cube root), ∜ (fourth root).

fn assert_true(cond:bool, msg:str):
  if not cond:
    std.print("FAIL: ", msg)

fn approx_eq(a:f64, b:f64, msg:str):
  let diff : mut = a - b
  if diff < 0.0:
    diff ← ⁻diff
  if diff > 0.0001:
    std.print("FAIL: ", msg, " (got ", a, " expected ", b, ")")

// --- Square root ---

fn test_sqrt_f64():
  let x: f64 = 25.0
  let r := √x
  approx_eq(r, 5.0, "√25.0")

fn test_sqrt_float():
  let x := 2.0
  let r := √x
  approx_eq(r, 1.4142, "√2.0")

fn test_sqrt_zero():
  let x: f64 = 0.0
  let r := √x
  approx_eq(r, 0.0, "√0.0")

// --- Cube root ---

fn test_cbrt_f64():
  let x: f64 = 27.0
  let r := ∛x
  approx_eq(r, 3.0, "∛27.0")

fn test_cbrt_float():
  let x := 8.0
  let r := ∛x
  approx_eq(r, 2.0, "∛8.0")

// --- Fourth root ---

fn test_fourth_root_f64():
  let x: f64 = 81.0
  let r := ∜x
  approx_eq(r, 3.0, "∜81.0")

fn test_fourth_root_float():
  let x := 16.0
  let r := ∜x
  approx_eq(r, 2.0, "∜16.0")

// --- Chained roots ---

fn test_sqrt_of_sqrt():
  let x := 256.0
  let r := √√x
  approx_eq(r, 4.0, "√√256.0 = ∜256.0")

// --- Integer operand rejected ---

fn test_sqrt_int_rejected():
  let x := 25
  @expect error "floating-point"
  let r : mut = √x

fn test_cbrt_int_rejected():
  let x := 27
  @expect error "floating-point"
  let r : mut = ∛x

fn test_fourth_root_int_rejected():
  let x := 16
  @expect error "floating-point"
  let r : mut = ∜x

// --- Roots with units ---

fn test_sqrt_unit():
  let area ¤meter×meter := 36.0
  let side := √area
  // √(36 m^2) = 6 m
  approx_eq(side, 6.0, "√(36 m^2) value")
  std.print(side)

fn test_sqrt_unit_incompatible():
  let d ¤meter := 9.0
  // √(m) has odd exponent, rejected
  @expect error "exponent"
  let r : mut = √d

fn test_cbrt_unit():
  let vol ¤meter×meter×meter := 125.0
  let side := ∛vol
  // ∛(125 m^3) = 5 m
  approx_eq(side, 5.0, "∛(125 m^3) value")
  std.print(side)

fn test_fourth_root_unit():
  let x ¤meter×meter×meter×meter := 625.0
  let r := ∜x
  // ∜(625 m^4) = 5 m (approximately)
  approx_eq(r, 5.0, "∜(625 m^4) value")

// --- Negation before root ---

fn test_neg_sqrt():
  let x := 9.0
  let r := ⁻√x
  approx_eq(r, ⁻3.0, "⁻√9.0")

@start
fn main():
  test_sqrt_f64()
  test_sqrt_float()
  test_sqrt_zero()
  test_cbrt_f64()
  test_cbrt_float()
  test_fourth_root_f64()
  test_fourth_root_float()
  test_sqrt_of_sqrt()
  test_sqrt_int_rejected()
  test_cbrt_int_rejected()
  test_fourth_root_int_rejected()
  test_sqrt_unit()
  test_sqrt_unit_incompatible()
  test_cbrt_unit()
  test_fourth_root_unit()
  test_neg_sqrt()
  std.print("root tests passed")
