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

@start
fn main → ∅:
    std.print("parameter pack tests passed")
