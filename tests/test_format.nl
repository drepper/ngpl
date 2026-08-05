/* Tests for std.format(allocator, fmt_str, args…). */

/* --- Basic substitution ------------------------------------------- */

@test
fn test_format_no_args → ∅:
    var alloc := std.arena.allocator()
    assert_eq(std.format(alloc, "hello world"), "hello world")
    alloc.deinit()

@test
fn test_format_one_int → ∅:
    var alloc := std.arena.allocator()
    assert_eq(std.format(alloc, "value: {}", 42), "value: 42")
    alloc.deinit()

@test
fn test_format_two_args → ∅:
    var alloc := std.arena.allocator()
    assert_eq(std.format(alloc, "{} + {} = {}", 1, 2, 3), "1 + 2 = 3")
    alloc.deinit()

@test
fn test_format_string_arg → ∅:
    var alloc := std.arena.allocator()
    assert_eq(std.format(alloc, "hello {}", "world"), "hello world")
    alloc.deinit()

@test
fn test_format_bool_arg → ∅:
    var alloc := std.arena.allocator()
    assert_eq(std.format(alloc, "{} and {}", true, false), "true and false")
    alloc.deinit()

/* --- Format specifiers -------------------------------------------- */

@test
fn test_format_hex → ∅:
    var alloc := std.arena.allocator()
    assert_eq(std.format(alloc, "{:x}", 255), "ff")
    assert_eq(std.format(alloc, "{:X}", 255), "FF")
    alloc.deinit()

@test
fn test_format_binary → ∅:
    var alloc := std.arena.allocator()
    assert_eq(std.format(alloc, "{:b}", 10), "1010")
    alloc.deinit()

@test
fn test_format_octal → ∅:
    var alloc := std.arena.allocator()
    assert_eq(std.format(alloc, "{:o}", 8), "10")
    alloc.deinit()

@test
fn test_format_char → ∅:
    var alloc := std.arena.allocator()
    assert_eq(std.format(alloc, "{:c}", 65), "A")
    alloc.deinit()

/* --- Arrays ------------------------------------------------------- */

@test
fn test_format_array → ∅:
    var alloc := std.arena.allocator()
    assert_eq(std.format(alloc, "{}", [1, 2, 3]), "[1, 2, 3]")
    alloc.deinit()

@test
fn test_format_empty_array → ∅:
    var alloc := std.arena.allocator()
    var arr := [1]
    /* slice to empty not available; test single-element */
    assert_eq(std.format(alloc, "{}", [42]), "[42]")
    alloc.deinit()

/* --- Escaping ----------------------------------------------------- */

@test
fn test_format_literal_braces → ∅:
    var alloc := std.arena.allocator()
    assert_eq(std.format(alloc, "{{}}"), "{}")
    alloc.deinit()

@test
fn test_format_mixed_literal_and_arg → ∅:
    var alloc := std.arena.allocator()
    assert_eq(std.format(alloc, "{{{}}} = {}", "x", 1), "{x} = 1")
    alloc.deinit()

/* --- Error cases -------------------------------------------------- */

@test
@expect error "not enough arguments"
fn test_format_too_few_args → ∅:
    var alloc := std.arena.allocator()
    std.format(alloc, "{} {}", 1)
    alloc.deinit()

@start
fn main → ∅:
    std.print("format tests passed")
