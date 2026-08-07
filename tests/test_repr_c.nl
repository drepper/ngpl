// Tests for the @repr(C) layout attribute on structs.
//
// Every expected size, alignment, and offset here was taken from what
// gcc reports for the equivalent C declaration on x86-64, so a change
// that breaks compatibility with the platform ABI fails these tests.

// ---------------------------------------------------------------------
// Layouts
// ---------------------------------------------------------------------

// struct { int32_t x; int64_t y; } -- four bytes of padding after x.
@repr(C)
struct Point:
    x : i32
    y : i64

@test
fn test_padding_between_fields() → ∅:
    assert_eq(Point.sizeof, 16)
    assert_eq(Point.alignof, 8)
    assert_eq(Point.offsetof("x"), 0)
    assert_eq(Point.offsetof("y"), 8)

// Byte fields need no padding at all.
@repr(C)
struct Packed3:
    a : u8
    b : u8
    c : u8

@test
fn test_all_bytes_are_dense() → ∅:
    assert_eq(Packed3.sizeof, 3)
    assert_eq(Packed3.alignof, 1)
    assert_eq(Packed3.offsetof("c"), 2)

// The size is rounded up so an array of the struct stays aligned: the
// trailing u8 is followed by three bytes of tail padding.
@repr(C)
struct Mixed:
    a : u8
    b : i32
    c : u8

@test
fn test_tail_padding() → ∅:
    assert_eq(Mixed.sizeof, 12)
    assert_eq(Mixed.alignof, 4)
    assert_eq(Mixed.offsetof("a"), 0)
    assert_eq(Mixed.offsetof("b"), 4)
    assert_eq(Mixed.offsetof("c"), 8)

// A fixed-size array takes its element's alignment, not its own size.
@repr(C)
struct Arr:
    tag : u8
    vals : i32[3]

@test
fn test_fixed_array_field() → ∅:
    assert_eq(Arr.sizeof, 16)
    assert_eq(Arr.alignof, 4)
    assert_eq(Arr.offsetof("vals"), 4)

// A nested @repr(C) struct contributes its own alignment.
@repr(C)
struct Nested:
    mark : u8
    p : Point

@test
fn test_nested_struct() → ∅:
    assert_eq(Nested.sizeof, 24)
    assert_eq(Nested.alignof, 8)
    assert_eq(Nested.offsetof("p"), 8)

@repr(C)
struct Wide:
    d : f64
    s : i16

@test
fn test_float_field() → ∅:
    assert_eq(Wide.sizeof, 16)
    assert_eq(Wide.alignof, 8)
    assert_eq(Wide.offsetof("s"), 8)

// An empty struct occupies no space, as in C.
@repr(C)
struct Empty:

@test
fn test_empty_struct() → ∅:
    assert_eq(Empty.sizeof, 0)
    assert_eq(Empty.alignof, 1)

// ---------------------------------------------------------------------
// The results carry the byte unit
// ---------------------------------------------------------------------

// Addition requires matching units, so these only succeed if the
// layout results really do carry the byte unit.
@test
fn test_layout_results_are_bytes() → ∅:
    assert_eq(Point.sizeof + 8¤byte, 24)
    assert_eq(Point.alignof + 8¤byte, 16)
    assert_eq(Point.offsetof("y") + 8¤byte, 16)

@expect error "incompatible units"
fn error_layout_is_not_a_count() → ∅:
    let n : mut = Point.sizeof + 8¤count

// ---------------------------------------------------------------------
// The attribute does not disturb ordinary struct use
// ---------------------------------------------------------------------

@repr(C)
struct Counter:
    value : i32

impl Counter:
    fn bumped(&self) → i32:
        self.value + 1

@test
fn test_repr_struct_behaves_normally() → ∅:
    let c : mut = Counter { value: 41 }
    assert_eq(c.value, 41)
    assert_eq(c.bumped(), 42)
    c.value ← 7
    assert_eq(c.value, 7)

// An instance answers for its type.
@test
fn test_instance_layout() → ∅:
    let p : mut = Point { x: 1, y: 2 }
    assert_eq(p.sizeof, 16)
    assert_eq(p.alignof, 8)

// ---------------------------------------------------------------------
// A struct without the attribute has no layout to report
// ---------------------------------------------------------------------

struct Loose:
    a : i32
    b : i64

@expect error "has no defined layout"
fn error_sizeof_without_repr() → ∅:
    let n : mut = Loose.sizeof

@expect error "has no defined layout"
fn error_alignof_without_repr() → ∅:
    let n : mut = Loose.alignof

@expect error "has no defined layout"
fn error_offsetof_without_repr() → ∅:
    let n : mut = Loose.offsetof("a")

// A struct with no layout is still a perfectly usable struct.
@test
fn test_loose_struct_still_works() → ∅:
    let l : mut = Loose { a: 1, b: 2 }
    assert_eq(l.a, 1)
    assert_eq(l.b, 2)

// ---------------------------------------------------------------------
// Field name errors
// ---------------------------------------------------------------------

@expect error "no field 'z'"
fn error_offsetof_unknown_field() → ∅:
    let n : mut = Point.offsetof("z")

@expect error "field name must be a str"
fn error_offsetof_not_a_string() → ∅:
    let n : mut = Point.offsetof(0)

@start
fn main() → ∅:
    std.print("repr(C) tests passed")
