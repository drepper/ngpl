/* Tests for enum types: definition, access, comparison, @flag enums,
 * bitwise flag operations, std.errors, and invalid operations.
 */

/* ---- basic enum definition and member access ----------------------------- */

enum Color:
    red
    green
    blue

@test
fn test_enum_member_access() → ∅:
    var c := Color.red
    assert_eq(c, Color.red)

@test
fn test_enum_sequential_values() → ∅:
    assert(Color.red == 0)
    assert(Color.green == 1)
    assert(Color.blue == 2)

@test
fn test_enum_equality() → ∅:
    var a := Color.red
    var b := Color.red
    var c := Color.blue
    assert(a == b)
    assert(not (a == c))
    assert(a != c)

/* ---- enum with explicit values ------------------------------------------- */

enum Status:
    ok = 0
    warning = 10
    error = 20
    fatal = 30

@test
fn test_enum_explicit_values() → ∅:
    assert(Status.ok == 0)
    assert(Status.warning == 10)
    assert(Status.error == 20)
    assert(Status.fatal == 30)

/* ---- enum with mixed auto and explicit ----------------------------------- */

enum Level:
    low
    medium
    high = 10
    critical

@test
fn test_enum_mixed_values() → ∅:
    assert(Level.low == 0)
    assert(Level.medium == 1)
    assert(Level.high == 10)
    assert(Level.critical == 11)

/* ---- enum with underlying type ------------------------------------------- */

enum SmallEnum : u8:
    a
    b
    c

@test
fn test_enum_underlying_type() → ∅:
    var x := SmallEnum.a
    assert(x == 0)
    assert(x == SmallEnum.a)

/* ---- @flag enum: powers of two ------------------------------------------- */

@flag
enum Perms:
    read
    write
    exec

@test
fn test_flag_auto_values() → ∅:
    assert(Perms.read == 1)
    assert(Perms.write == 2)
    assert(Perms.exec == 4)

@test
fn test_flag_nil_auto_created() → ∅:
    assert(Perms.nil == 0)

@test
fn test_flag_combine_or() → ∅:
    var rw := Perms.read | Perms.write
    assert(rw == 3)

@test
fn test_flag_combine_all() → ∅:
    var all := Perms.read | Perms.write | Perms.exec
    assert(all == 7)

@test
fn test_flag_and() → ∅:
    var rw := Perms.read | Perms.write
    var r := rw & Perms.read
    assert_eq(r, Perms.read)

@test
fn test_flag_xor() → ∅:
    var rw := Perms.read | Perms.write
    var toggled := rw ^ Perms.write
    assert_eq(toggled, Perms.read)

@test
fn test_flag_not() → ∅:
    var rw := Perms.read | Perms.write
    var notrw := ~rw
    assert_eq(notrw, Perms.exec)

@test
fn test_flag_and_test_membership() → ∅:
    var rw := Perms.read | Perms.write
    var has_read := (rw & Perms.read) == Perms.read
    var has_exec := (rw & Perms.exec) == Perms.exec
    assert(has_read)
    assert(not has_exec)

/* ---- @flag enum with explicit values ------------------------------------- */

@flag
enum Flags:
    a = 1
    b = 4
    c
    d

@test
fn test_flag_explicit_and_auto() → ∅:
    assert(Flags.a == 1)
    assert(Flags.b == 4)
    assert(Flags.c == 8)
    assert(Flags.d == 16)

/* ---- @flag enum with explicit zero (no auto nil) ------------------------- */

@flag
enum Mode:
    off = 0
    read = 1
    write = 2

@test
fn test_flag_explicit_zero_no_nil() → ∅:
    assert(Mode.off == 0)
    assert(Mode.read == 1)

/* ---- std.errors enum ----------------------------------------------------- */

@test
fn test_std_errors_runtime() → ∅:
    var e := std.errors.division_by_zero
    assert(e == 100)
    assert_eq(e, std.errors.division_by_zero)

@test
fn test_std_errors_compile() → ∅:
    assert(std.errors.type_mismatch == 200)
    assert(std.errors.unknown_type == 201)
    assert(std.errors.syntax_error == 202)

@test
fn test_std_errors_library() → ∅:
    assert(std.errors.file_not_found == 300)
    assert(std.errors.permission_denied == 301)
    assert(std.errors.io_error == 302)

@test
fn test_std_errors_grouping() → ∅:
    /* Runtime errors are in 100-199 */
    var div := std.errors.division_by_zero
    assert(div == 100 ∧ 100 <= 199)
    /* Compile errors are in 200-299 */
    var typ := std.errors.type_mismatch
    assert(typ == 200 ∧ 200 <= 299)
    /* Library errors are in 300-399 */
    var fnf := std.errors.file_not_found
    assert(fnf == 300 ∧ 300 <= 399)

/* ---- invalid operations on non-flag enums -------------------------------- */

@expect error "bitwise operations require @flag enum"
fn error_bitor_non_flag() → ∅:
    var a := Color.red
    var b := Color.green
    var c := a | b

@expect error "bitwise operations require @flag enum"
fn error_bitand_non_flag() → ∅:
    var a := Color.red
    var b := Color.green
    var c := a & b

@expect error "bitwise operations require @flag enum"
fn error_bitxor_non_flag() → ∅:
    var a := Color.red
    var b := Color.green
    var c := a ^ b

@expect error "bitwise-not requires @flag enum"
fn error_bitnot_non_flag() → ∅:
    var a := Color.red
    var b := ~a

/* ---- cross-enum comparison error ----------------------------------------- */

@expect error "cannot compare enum"
fn error_cross_enum_compare() → ∅:
    var a := Color.red
    var b := Status.ok
    var x := a == b

@expect error "cannot combine enum"
fn error_cross_enum_bitor() → ∅:
    var a := Perms.read
    var b := Flags.a
    var c := a | b

@start
fn main() → ∅:
    std.print("enum tests passed")
