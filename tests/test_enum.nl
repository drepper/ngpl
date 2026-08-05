/* Tests for enum types: definition, access, comparison, @flag enums,
 * bitwise flag operations, std.errors, and invalid operations.
 */

/* ---- basic enum definition and member access ----------------------------- */

enum Color:
    red
    green
    blue

@test
fn test_enum_member_access -> none:
    var c := Color.red
    assert_eq(c, Color.red)

@test
fn test_enum_sequential_values -> none:
    assert_eq(Color.red == 0, true)
    assert_eq(Color.green == 1, true)
    assert_eq(Color.blue == 2, true)

@test
fn test_enum_equality -> none:
    var a := Color.red
    var b := Color.red
    var c := Color.blue
    assert_eq(a == b, true)
    assert_eq(a == c, false)
    assert_eq(a != c, true)

/* ---- enum with explicit values ------------------------------------------- */

enum Status:
    ok = 0
    warning = 10
    error = 20
    fatal = 30

@test
fn test_enum_explicit_values -> none:
    assert_eq(Status.ok == 0, true)
    assert_eq(Status.warning == 10, true)
    assert_eq(Status.error == 20, true)
    assert_eq(Status.fatal == 30, true)

/* ---- enum with mixed auto and explicit ----------------------------------- */

enum Level:
    low
    medium
    high = 10
    critical

@test
fn test_enum_mixed_values -> none:
    assert_eq(Level.low == 0, true)
    assert_eq(Level.medium == 1, true)
    assert_eq(Level.high == 10, true)
    assert_eq(Level.critical == 11, true)

/* ---- enum with underlying type ------------------------------------------- */

enum SmallEnum : u8:
    a
    b
    c

@test
fn test_enum_underlying_type -> none:
    var x := SmallEnum.a
    assert_eq(x == 0, true)
    assert_eq(x == SmallEnum.a, true)

/* ---- @flag enum: powers of two ------------------------------------------- */

@flag
enum Perms:
    read
    write
    exec

@test
fn test_flag_auto_values -> none:
    assert_eq(Perms.read == 1, true)
    assert_eq(Perms.write == 2, true)
    assert_eq(Perms.exec == 4, true)

@test
fn test_flag_nil_auto_created -> none:
    assert_eq(Perms.nil == 0, true)

@test
fn test_flag_combine_or -> none:
    var rw := Perms.read | Perms.write
    assert_eq(rw == 3, true)

@test
fn test_flag_combine_all -> none:
    var all := Perms.read | Perms.write | Perms.exec
    assert_eq(all == 7, true)

@test
fn test_flag_and -> none:
    var rw := Perms.read | Perms.write
    var r := rw & Perms.read
    assert_eq(r, Perms.read)

@test
fn test_flag_xor -> none:
    var rw := Perms.read | Perms.write
    var toggled := rw ^ Perms.write
    assert_eq(toggled, Perms.read)

@test
fn test_flag_not -> none:
    var rw := Perms.read | Perms.write
    var notrw := ~rw
    assert_eq(notrw, Perms.exec)

@test
fn test_flag_and_test_membership -> none:
    var rw := Perms.read | Perms.write
    var has_read := (rw & Perms.read) == Perms.read
    var has_exec := (rw & Perms.exec) == Perms.exec
    assert_eq(has_read, true)
    assert_eq(has_exec, false)

/* ---- @flag enum with explicit values ------------------------------------- */

@flag
enum Flags:
    a = 1
    b = 4
    c
    d

@test
fn test_flag_explicit_and_auto -> none:
    assert_eq(Flags.a == 1, true)
    assert_eq(Flags.b == 4, true)
    assert_eq(Flags.c == 8, true)
    assert_eq(Flags.d == 16, true)

/* ---- @flag enum with explicit zero (no auto nil) ------------------------- */

@flag
enum Mode:
    off = 0
    read = 1
    write = 2

@test
fn test_flag_explicit_zero_no_nil -> none:
    assert_eq(Mode.off == 0, true)
    assert_eq(Mode.read == 1, true)

/* ---- std.errors enum ----------------------------------------------------- */

@test
fn test_std_errors_runtime -> none:
    var e := std.errors.division_by_zero
    assert_eq(e == 100, true)
    assert_eq(e, std.errors.division_by_zero)

@test
fn test_std_errors_compile -> none:
    assert_eq(std.errors.type_mismatch == 200, true)
    assert_eq(std.errors.unknown_type == 201, true)
    assert_eq(std.errors.syntax_error == 202, true)

@test
fn test_std_errors_library -> none:
    assert_eq(std.errors.file_not_found == 300, true)
    assert_eq(std.errors.permission_denied == 301, true)
    assert_eq(std.errors.io_error == 302, true)

@test
fn test_std_errors_grouping -> none:
    /* Runtime errors are in 100-199 */
    var div := std.errors.division_by_zero
    assert_eq(div == 100 ∧ 100 <= 199, true)
    /* Compile errors are in 200-299 */
    var typ := std.errors.type_mismatch
    assert_eq(typ == 200 ∧ 200 <= 299, true)
    /* Library errors are in 300-399 */
    var fnf := std.errors.file_not_found
    assert_eq(fnf == 300 ∧ 300 <= 399, true)

/* ---- invalid operations on non-flag enums -------------------------------- */

@expect error "bitwise operations require @flag enum"
fn error_bitor_non_flag -> none:
    var a := Color.red
    var b := Color.green
    var c := a | b

@expect error "bitwise operations require @flag enum"
fn error_bitand_non_flag -> none:
    var a := Color.red
    var b := Color.green
    var c := a & b

@expect error "bitwise operations require @flag enum"
fn error_bitxor_non_flag -> none:
    var a := Color.red
    var b := Color.green
    var c := a ^ b

@expect error "bitwise-not requires @flag enum"
fn error_bitnot_non_flag -> none:
    var a := Color.red
    var b := ~a

/* ---- cross-enum comparison error ----------------------------------------- */

@expect error "cannot compare enum"
fn error_cross_enum_compare -> none:
    var a := Color.red
    var b := Status.ok
    var x := a == b

@expect error "cannot combine enum"
fn error_cross_enum_bitor -> none:
    var a := Perms.read
    var b := Flags.a
    var c := a | b

@start
fn main -> none:
    std.print("enum tests passed")
