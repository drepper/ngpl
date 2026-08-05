/* Tests for parameter packs. */

/* Sum all pack arguments (untyped pack). */
fn sum_all acc : int, rest… : int → int:
    var i : int = 0
    var s := acc
    while i < rest.sizeof:
        s ← s + rest[i]
        i ← i + 1
    s

/* Count the number of pack elements. */
fn count_args args… → int:
    args.sizeof

/* Return the first pack element. */
fn first_of args… : T':
    args[0]

/* Apply a function to each pack element and sum. */
fn apply_sum f, args… : int → int:
    var s : int = 0
    var i : int = 0
    while i < args.sizeof:
        s ← s + f(args[i])
        i ← i + 1
    s

@test
fn test_sum_basic → ∅:
    assert_eq(sum_all(1, 2, 3, 4), 10)

@test
fn test_sum_single → ∅:
    assert_eq(sum_all(100), 100)

@test
fn test_count_empty → ∅:
    assert_eq(count_args(), 0)

@test
fn test_count_several → ∅:
    assert_eq(count_args(1, 2, 3), 3)

@test
fn test_first → ∅:
    assert_eq(first_of(42, 99), 42)
    assert_eq(first_of("hello", "world"), "hello")

@test
fn test_typeof_pack → ∅:
    var r := first_of(42)
    assert_eq(@typeof(r), @typeof(0))

fn double x : int → int:
    x * 2

@test
fn test_apply_sum → ∅:
    assert_eq(apply_sum(double, 1, 2, 3), 12)

/* --- Type mismatch tests ------------------------------------------ */

@test
@expect error "expected int.*got StrValue"
fn test_typed_pack_rejects_string → ∅:
    sum_all(1, "oops")

@test
@expect error "expected int.*got BoolValue"
fn test_typed_pack_rejects_bool → ∅:
    sum_all(1, 2, true)

@test
@expect error "expected int.*got StrValue"
fn test_apply_sum_rejects_string → ∅:
    apply_sum(double, 1, "bad", 3)

@test
@expect error "expected int.*got BoolValue"
fn test_apply_sum_rejects_bool → ∅:
    apply_sum(double, 1, true)

/* --- Edge cases --------------------------------------------------- */

/* Pack with a single element. */
@test
fn test_single_pack_element → ∅:
    assert_eq(count_args(42), 1)
    assert_eq(first_of(99), 99)

/* Untyped pack can also be empty. */
fn untyped_count args… → int:
    args.sizeof

@test
fn test_empty_untyped_pack → ∅:
    assert_eq(untyped_count(), 0)

/* Multiple elements with different types via generic pack. */
@test
fn test_generic_pack_mixed_types → ∅:
    assert_eq(@typeof(first_of(42, "hello")), @typeof(0))
    assert_eq(@typeof(first_of("hello", 42)), @typeof(""))

/* Access several pack elements by index. */
fn second_of args… : T':
    args[1]

@test
fn test_pack_index_access → ∅:
    assert_eq(second_of(10, 20, 30), 20)
    assert_eq(second_of("a", "b", "c"), "b")

/* Sum via concrete-typed pack. */
fn int_sum vals… : int → int:
    var s : int = 0
    var i : int = 0
    while i < vals.sizeof:
        s ← s + vals[i]
        i ← i + 1
    s

@test
fn test_int_sum → ∅:
    assert_eq(int_sum(), 0)
    assert_eq(int_sum(5), 5)
    assert_eq(int_sum(1, 2, 3, 4, 5), 15)

/* Pack with typed regular params and typed pack. */
fn prepend_and_sum base : int, extra… : int → int:
    var s := base
    var i : int = 0
    while i < extra.sizeof:
        s ← s + extra[i]
        i ← i + 1
    s

@test
fn test_prepend_and_sum → ∅:
    assert_eq(prepend_and_sum(100), 100)
    assert_eq(prepend_and_sum(100, 1, 2, 3), 106)

@test
@expect error "expected int.*got StrValue"
fn test_prepend_and_sum_rejects_bad_pack → ∅:
    prepend_and_sum(100, "bad")

/* --- @sizeof tests ------------------------------------------------ */

/* @sizeof on packs. */
fn sizeof_pack args… → int:
    @sizeof(args)

@test
fn test_sizeof_pack_empty → ∅:
    assert_eq(sizeof_pack(), 0)

@test
fn test_sizeof_pack_several → ∅:
    assert_eq(sizeof_pack(1, 2, 3), 3)

/* @sizeof on arrays. */
@test
fn test_sizeof_array → ∅:
    var arr := [10, 20, 30, 40]
    assert_eq(@sizeof(arr), 4)

/* @sizeof on strings. */
@test
fn test_sizeof_string → ∅:
    assert_eq(@sizeof("hello"), 5)
    assert_eq(@sizeof(""), 0)

/* @sizeof matches .sizeof on arrays and packs. */
@test
fn test_sizeof_matches_dot_sizeof → ∅:
    var arr := [1, 2, 3]
    assert_eq(@sizeof(arr), arr.sizeof)

fn sizeof_both args… : int → int:
    assert_eq(@sizeof(args), args.sizeof)
    @sizeof(args)

@test
fn test_sizeof_pack_matches_dot → ∅:
    assert_eq(sizeof_both(5, 6), 2)

/* @sizeof rejects non-containers. */
@test
@expect error "@sizeof.*expected"
fn test_sizeof_rejects_int → ∅:
    @sizeof(42)

@test
@expect error "@sizeof.*expected"
fn test_sizeof_rejects_bool → ∅:
    @sizeof(true)

@start
fn main → ∅:
    std.print("parameter pack tests passed")
