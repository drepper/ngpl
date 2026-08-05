/* Tests for binary logic operations: ∧ ∨ ⊕ ⊼ ⊽ ¬
 *
 * These operate on logical truth values.  For bool operands the value
 * is used directly; for integers a nonzero test is applied first.
 * All results are bool (true/false).
 */

/* ---- ∧ (logic AND) ------------------------------------------------------ */

@test
fn test_and_true_true -> ø:
    assert_eq(true ∧ true, true)

@test
fn test_and_true_false -> ø:
    assert_eq(true ∧ false, false)

@test
fn test_and_false_true -> ø:
    assert_eq(false ∧ true, false)

@test
fn test_and_false_false -> ø:
    assert_eq(false ∧ false, false)

/* ---- ∨ (logic OR) ------------------------------------------------------- */

@test
fn test_or_true_false -> ø:
    assert_eq(true ∨ false, true)

@test
fn test_or_false_false -> ø:
    assert_eq(false ∨ false, false)

@test
fn test_or_false_true -> ø:
    assert_eq(false ∨ true, true)

/* ---- ⊕ (logic XOR) ----------------------------------------------------- */

@test
fn test_xor_true_true -> ø:
    assert_eq(true ⊕ true, false)

@test
fn test_xor_true_false -> ø:
    assert_eq(true ⊕ false, true)

@test
fn test_xor_false_false -> ø:
    assert_eq(false ⊕ false, false)

/* ---- ⊼ (logic NAND) ---------------------------------------------------- */

@test
fn test_nand_true_true -> ø:
    assert_eq(true ⊼ true, false)

@test
fn test_nand_true_false -> ø:
    assert_eq(true ⊼ false, true)

@test
fn test_nand_false_false -> ø:
    assert_eq(false ⊼ false, true)

/* ---- ⊽ (logic NOR) ----------------------------------------------------- */

@test
fn test_nor_false_false -> ø:
    assert_eq(false ⊽ false, true)

@test
fn test_nor_true_false -> ø:
    assert_eq(true ⊽ false, false)

@test
fn test_nor_true_true -> ø:
    assert_eq(true ⊽ true, false)

/* ---- ¬ (logic NOT) ------------------------------------------------------ */

@test
fn test_not_true -> ø:
    assert_eq(¬true, false)

@test
fn test_not_false -> ø:
    assert_eq(¬false, true)

/* ---- integer operands: nonzero test ------------------------------------- */

@test
fn test_and_int_nonzero -> ø:
    var a : i32 = 42
    var b : i32 = 7
    assert_eq(a ∧ b, true)

@test
fn test_and_int_zero -> ø:
    var a : i32 = 42
    var b : i32 = 0
    assert_eq(a ∧ b, false)

@test
fn test_or_int_one_zero -> ø:
    var a : i32 = 0
    var b : i32 = 1
    assert_eq(a ∨ b, true)

@test
fn test_xor_int_both_nonzero -> ø:
    var a : i32 = 5
    var b : i32 = 3
    assert_eq(a ⊕ b, false)

@test
fn test_xor_int_one_zero -> ø:
    var a : i32 = 5
    var b : i32 = 0
    assert_eq(a ⊕ b, true)

@test
fn test_not_int_nonzero -> ø:
    var x : i32 = 100
    assert_eq(¬x, false)

@test
fn test_not_int_zero -> ø:
    var x : i32 = 0
    assert_eq(¬x, true)

@test
fn test_nand_int -> ø:
    var a : i32 = 1
    var b : i32 = 1
    assert_eq(a ⊼ b, false)
    var c : i32 = 0
    assert_eq(a ⊼ c, true)

@test
fn test_nor_int -> ø:
    var a : i32 = 0
    var b : i32 = 0
    assert_eq(a ⊽ b, true)
    var c : i32 = 1
    assert_eq(a ⊽ c, false)

/* ---- unsigned integer operands ------------------------------------------ */

@test
fn test_and_u8 -> ø:
    var a : u8 = 255
    var b : u8 = 0
    assert_eq(a ∧ b, false)
    assert_eq(a ∧ a, true)

/* ---- precedence: ∧ binds tighter than ∨ -------------------------------- */

@test
fn test_precedence_and_or -> ø:
    /* false ∨ true ∧ true  =  false ∨ (true ∧ true)  =  true */
    assert_eq(false ∨ true ∧ true, true)
    /* true ∧ false ∨ true  =  (true ∧ false) ∨ true  =  true */
    assert_eq(true ∧ false ∨ true, true)
    /* true ∧ false ∨ false  =  (true ∧ false) ∨ false  =  false */
    assert_eq(true ∧ false ∨ false, false)

/* ---- precedence: ⊕ is between ∧ and ∨ ---------------------------------- */

@test
fn test_precedence_xor -> ø:
    /* true ∧ true ⊕ true ∧ true  =  (true ∧ true) ⊕ (true ∧ true)  =  false */
    assert_eq(true ∧ true ⊕ true ∧ true, false)

/* ---- element-wise on arrays --------------------------------------------- */

@test
fn test_and_array -> ø:
    var a : i32[3] = 0
    a[0] ← 1; a[1] ← 0; a[2] ← 5
    var b : i32[3] = 0
    b[0] ← 3; b[1] ← 0; b[2] ← 0
    var r := a ∧ b
    assert_eq(r[0], true)
    assert_eq(r[1], false)
    assert_eq(r[2], false)

@test
fn test_or_array -> ø:
    var a : i32[3] = 0
    a[0] ← 1; a[1] ← 0; a[2] ← 0
    var b : i32[3] = 0
    b[0] ← 0; b[1] ← 0; b[2] ← 7
    var r := a ∨ b
    assert_eq(r[0], true)
    assert_eq(r[1], false)
    assert_eq(r[2], true)

@test
fn test_xor_array -> ø:
    var a : i32[3] = 0
    a[0] ← 1; a[1] ← 0; a[2] ← 5
    var b : i32[3] = 0
    b[0] ← 3; b[1] ← 0; b[2] ← 0
    var r := a ⊕ b
    assert_eq(r[0], false)
    assert_eq(r[1], false)
    assert_eq(r[2], true)

/* ---- logic ops combined with comparison --------------------------------- */

@test
fn test_logic_with_comparison -> ø:
    var x : i32 = 10
    var y : i32 = 20
    /* (x < y) ∧ (y > 0)  =  true ∧ true  =  true */
    assert_eq(x < y ∧ y > 0, true)
    /* (x > y) ∨ (y == 20)  =  false ∨ true  =  true */
    assert_eq(x > y ∨ y == 20, true)

@start
fn main -> ø:
    std.print("logic tests passed")
