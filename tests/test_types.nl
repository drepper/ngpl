/* Test type coercion, widening, and optional parameters. */

/* Untyped int coerced to u32 on function call. */
@test
fn test_widen_to_u32 -> ø:
    var result := add_u32(100, 200)
    assert_eq(result, 300)

fn add_u32 a : u32, b : u32 -> u32:
    a + b

/* Optional parameter accepts both value and ø. */
@test
fn test_optional_param_some -> ø:
    assert_eq(unwrap_or_zero(42), 42)

@test
fn test_optional_param_none -> ø:
    assert_eq(unwrap_or_zero(ø), 0)

fn unwrap_or_zero x : int? -> int:
    x ?? 0

@start
fn main -> ø:
    std.print("type tests passed")
