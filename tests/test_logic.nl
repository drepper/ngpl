/* Tests for binary logic operations: ∧ ∨ ⊕ ⊼ ⊽ ¬
 *
 * These operate on logical truth values.  For bool operands the value
 * is used directly; for integers a nonzero test is applied first.
 * All results are bool (true/false).
 */

/* ---- ∧ (logic AND) ------------------------------------------------------ */

@test
fn test_and_true_true() → ∅:
    assert(true ∧ true)

@test
fn test_and_true_false() → ∅:
    assert(not (true ∧ false))

@test
fn test_and_false_true() → ∅:
    assert(not (false ∧ true))

@test
fn test_and_false_false() → ∅:
    assert(not (false ∧ false))

/* ---- ∨ (logic OR) ------------------------------------------------------- */

@test
fn test_or_true_false() → ∅:
    assert(true ∨ false)

@test
fn test_or_false_false() → ∅:
    assert(not (false ∨ false))

@test
fn test_or_false_true() → ∅:
    assert(false ∨ true)

/* ---- ⊕ (logic XOR) ----------------------------------------------------- */

@test
fn test_xor_true_true() → ∅:
    assert(not (true ⊕ true))

@test
fn test_xor_true_false() → ∅:
    assert(true ⊕ false)

@test
fn test_xor_false_false() → ∅:
    assert(not (false ⊕ false))

/* ---- ⊼ (logic NAND) ---------------------------------------------------- */

@test
fn test_nand_true_true() → ∅:
    assert(not (true ⊼ true))

@test
fn test_nand_true_false() → ∅:
    assert(true ⊼ false)

@test
fn test_nand_false_false() → ∅:
    assert(false ⊼ false)

/* ---- ⊽ (logic NOR) ----------------------------------------------------- */

@test
fn test_nor_false_false() → ∅:
    assert(false ⊽ false)

@test
fn test_nor_true_false() → ∅:
    assert(not (true ⊽ false))

@test
fn test_nor_true_true() → ∅:
    assert(not (true ⊽ true))

/* ---- ¬ (logic NOT) ------------------------------------------------------ */

@test
fn test_not_true() → ∅:
    assert(not (¬true))

@test
fn test_not_false() → ∅:
    assert(¬false)

/* ---- integer operands: nonzero test ------------------------------------- */

@test
fn test_and_int_nonzero() → ∅:
    var a : i32 = 42
    var b : i32 = 7
    assert(a ∧ b)

@test
fn test_and_int_zero() → ∅:
    var a : i32 = 42
    var b : i32 = 0
    assert(not (a ∧ b))

@test
fn test_or_int_one_zero() → ∅:
    var a : i32 = 0
    var b : i32 = 1
    assert(a ∨ b)

@test
fn test_xor_int_both_nonzero() → ∅:
    var a : i32 = 5
    var b : i32 = 3
    assert(not (a ⊕ b))

@test
fn test_xor_int_one_zero() → ∅:
    var a : i32 = 5
    var b : i32 = 0
    assert(a ⊕ b)

@test
fn test_not_int_nonzero() → ∅:
    var x : i32 = 100
    assert(not (¬x))

@test
fn test_not_int_zero() → ∅:
    var x : i32 = 0
    assert(¬x)

@test
fn test_nand_int() → ∅:
    var a : i32 = 1
    var b : i32 = 1
    assert(not (a ⊼ b))
    var c : i32 = 0
    assert(a ⊼ c)

@test
fn test_nor_int() → ∅:
    var a : i32 = 0
    var b : i32 = 0
    assert(a ⊽ b)
    var c : i32 = 1
    assert(not (a ⊽ c))

/* ---- unsigned integer operands ------------------------------------------ */

@test
fn test_and_u8() → ∅:
    var a : u8 = 255
    var b : u8 = 0
    assert(not (a ∧ b))
    assert(a ∧ a)

/* ---- precedence: ∧ binds tighter than ∨ -------------------------------- */

@test
fn test_precedence_and_or() → ∅:
    /* false ∨ true ∧ true  =  false ∨ (true ∧ true)  =  true */
    assert(false ∨ true ∧ true)
    /* true ∧ false ∨ true  =  (true ∧ false) ∨ true  =  true */
    assert(true ∧ false ∨ true)
    /* true ∧ false ∨ false  =  (true ∧ false) ∨ false  =  false */
    assert(not (true ∧ false ∨ false))

/* ---- precedence: ⊕ is between ∧ and ∨ ---------------------------------- */

@test
fn test_precedence_xor() → ∅:
    /* true ∧ true ⊕ true ∧ true  =  (true ∧ true) ⊕ (true ∧ true)  =  false */
    assert(not (true ∧ true ⊕ true ∧ true))

/* ---- element-wise on arrays --------------------------------------------- */

@test
fn test_and_array() → ∅:
    var a : i32[3] = 0
    a[0] ← 1; a[1] ← 0; a[2] ← 5
    var b : i32[3] = 0
    b[0] ← 3; b[1] ← 0; b[2] ← 0
    var r := a ∧ b
    assert(r[0])
    assert(not r[1])
    assert(not r[2])

@test
fn test_or_array() → ∅:
    var a : i32[3] = 0
    a[0] ← 1; a[1] ← 0; a[2] ← 0
    var b : i32[3] = 0
    b[0] ← 0; b[1] ← 0; b[2] ← 7
    var r := a ∨ b
    assert(r[0])
    assert(not r[1])
    assert(r[2])

@test
fn test_xor_array() → ∅:
    var a : i32[3] = 0
    a[0] ← 1; a[1] ← 0; a[2] ← 5
    var b : i32[3] = 0
    b[0] ← 3; b[1] ← 0; b[2] ← 0
    var r := a ⊕ b
    assert(not r[0])
    assert(not r[1])
    assert(r[2])

/* ---- logic ops combined with comparison --------------------------------- */

@test
fn test_logic_with_comparison() → ∅:
    var x : i32 = 10
    var y : i32 = 20
    /* (x < y) ∧ (y > 0)  =  true ∧ true  =  true */
    assert(x < y ∧ y > 0)
    /* (x > y) ∨ (y == 20)  =  false ∨ true  =  true */
    assert(x > y ∨ y == 20)

@start
fn main() → ∅:
    std.print("logic tests passed")
