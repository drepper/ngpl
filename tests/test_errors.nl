/* Error and warning detection tests using @expect annotations.
 *
 * Function-level @expect: the interpreter tries to parse and evaluate
 * the function; produced diagnostics are matched against expectations.
 *
 * Statement-level @expect: the annotation appears before a statement
 * inside a function body; diagnostics from that single statement are
 * captured and matched.
 */

/* --- const immutability --------------------------------------------------- */

@expect error "cannot assign to const variable 'x'"
fn error_const_assign -> none:
    const x := 42
    x ← 99

@expect error "cannot redefine const variable 'x'"
fn error_const_redef -> none:
    const x := 42
    var x := 99

/* --- foreach immutability ------------------------------------------------- */

@expect error "cannot assign to foreach variable 'i'"
fn error_foreach_assign -> none:
    foreach i = 1…3:
        i ← i + 1

/* foreach variable redefinition is a warning, not an error.
 * The new variable shadows the loop variable after the redefinition. */
@test
fn warn_foreach_redef -> none:
    var total := 0
    foreach i = 1…3:
        @expect warning "redefinition of foreach variable 'i'"
        var i := 99
        total ← total + i
    assert_eq(total, 297)

/* --- fast type restrictions ----------------------------------------------- */

@expect error "fast type.*cannot be used as array element"
fn error_fast_array -> none:
    var arr : u8fast[10] = 0
    std.print(arr[0])

/* --- type mismatch -------------------------------------------------------- */

@expect error "assert_eq failed"
fn error_assert_mismatch -> none:
    assert_eq(1, 2)

/* --- division by zero ----------------------------------------------------- */

@expect error "division by zero"
fn error_div_zero -> none:
    var x := 10 / 0

/* --- parse errors --------------------------------------------------------- */

@expect error "unexpected token: 'fn'"
fn error_nested_fn -> none:
    fn inner -> none:
        std.print("bad")

/* --- unknown types -------------------------------------------------------- */

@expect error "unknown type 'i1'"
fn error_unknown_type_var -> none:
    var x : i1 = 0

@start
fn main -> none:
    std.print("error tests passed")
