/* Tests for generic functions. */

/* Identity function: return type follows parameter type. */
fn identity x : T' → T':
    x

/* Both parameters must have the same type. */
fn add_g a : T', b : T' → T':
    a + b

/* Different generic names allow different argument types. */
fn pick_first a : T', b : U' → T':
    a

fn pick_second a : T', b : U' → U':
    b

/* Generic used only in parameters, concrete return type. */
fn to_bool x : T' → bool:
    x != 0

/* ------------------------------------------------------------------ */

@test
fn test_identity_int → ∅:
    assert_eq(identity(42), 42)

@test
fn test_identity_bool → ∅:
    assert_eq(identity(true), true)
    assert_eq(identity(false), false)

@test
fn test_identity_string → ∅:
    assert_eq(identity("hello"), "hello")

@test
fn test_identity_typed_int → ∅:
    var x : i32 = 7
    var r := identity(x)
    assert_eq(r, 7)

@test
fn test_add_same_type → ∅:
    assert_eq(add_g(10, 20), 30)

@test
fn test_add_typed → ∅:
    var a : u32 = 100
    var b : u32 = 200
    assert_eq(add_g(a, b), 300)

@test
fn test_different_generics → ∅:
    assert_eq(pick_first(42, "hello"), 42)
    assert_eq(pick_first("world", 99), "world")
    assert_eq(pick_second(1, true), true)

@test
fn test_generic_with_concrete_return → ∅:
    assert_eq(to_bool(1), true)
    assert_eq(to_bool(0), false)

@test
fn test_generic_type_mismatch → ∅:
    var a : i32 = 1
    var b : u32 = 2
    @expect error "generic type T'"
    add_g(a, b)

@test
fn test_generic_curry → ∅:
    var add10 := add_g(10)
    assert_eq(add10(20), 30)

@start
fn main → ∅:
    std.print("generic tests passed")
