// Tests for the array member functions: push, pop, insert, remove, get.
//
// The set and the semantics follow Rust's Vec.  Where Rust returns an
// Option this returns an optional, and where Rust panics this raises.

// ---------------------------------------------------------------------
// push and pop work at the end
// ---------------------------------------------------------------------

@test
fn test_push_appends() → ∅:
    let v : mut = [1, 2, 3]
    v.push(4)
    assert_eq(v.sizeof, 4)
    assert_eq(v[3], 4)

@test
fn test_push_onto_empty() → ∅:
    let v : mut = []
    v.push(7)
    assert_eq(v.sizeof, 1)
    assert_eq(v[0], 7)

@test
fn test_pop_returns_last() → ∅:
    let v : mut = [1, 2, 3]
    assert_eq(v.pop(), ∃(3))
    assert_eq(v.sizeof, 2)
    assert_eq(v[1], 2)

// Popping an array that may be empty is an ordinary thing to do, so it
// answers with an optional rather than failing.
@test
fn test_pop_empty_is_none() → ∅:
    let v : mut = []
    assert_eq(v.pop(), ∅)

@test
fn test_pop_until_empty() → ∅:
    let v : mut = [1, 2]
    assert_eq(v.pop(), ∃(2))
    assert_eq(v.pop(), ∃(1))
    assert_eq(v.pop(), ∅)
    assert_eq(v.sizeof, 0)

// push then pop leaves the array as it was.
@test
fn test_push_pop_round_trip() → ∅:
    let v : mut = [1, 2]
    v.push(3)
    assert_eq(v.pop(), ∃(3))
    assert_eq(v.sizeof, 2)
    assert_eq(v[0], 1)
    assert_eq(v[1], 2)

// ---------------------------------------------------------------------
// insert and remove work at an index
// ---------------------------------------------------------------------

@test
fn test_insert_at_front_shifts_right() → ∅:
    let v : mut = [1, 2, 3]
    v.insert(0, 0)
    assert_eq(v.sizeof, 4)
    assert_eq(v[0], 0)
    assert_eq(v[1], 1)
    assert_eq(v[3], 3)

@test
fn test_insert_in_middle() → ∅:
    let v : mut = [1, 3]
    v.insert(1, 2)
    assert_eq(v[0], 1)
    assert_eq(v[1], 2)
    assert_eq(v[2], 3)

// Inserting at the length appends, as in Rust.
@test
fn test_insert_at_length_appends() → ∅:
    let v : mut = [1, 2]
    v.insert(2, 3)
    assert_eq(v.sizeof, 3)
    assert_eq(v[2], 3)

@test
fn test_remove_returns_element_and_shifts_left() → ∅:
    let v : mut = [1, 2, 3]
    assert_eq(v.remove(1), 2)
    assert_eq(v.sizeof, 2)
    assert_eq(v[0], 1)
    assert_eq(v[1], 3)

@test
fn test_remove_first() → ∅:
    let v : mut = [1, 2]
    assert_eq(v.remove(0), 1)
    assert_eq(v[0], 2)

@test
fn test_remove_last() → ∅:
    let v : mut = [1, 2]
    assert_eq(v.remove(1), 2)
    assert_eq(v.sizeof, 1)

// insert then remove at the same index leaves the array as it was.
@test
fn test_insert_remove_round_trip() → ∅:
    let v : mut = [1, 2, 3]
    v.insert(1, 9)
    assert_eq(v.remove(1), 9)
    assert_eq(v.sizeof, 3)
    assert_eq(v[1], 2)

// ---------------------------------------------------------------------
// get reads without risking a failure
// ---------------------------------------------------------------------

@test
fn test_get_in_range() → ∅:
    let v : mut = [10, 20, 30]
    assert_eq(v.get(0), ∃(10))
    assert_eq(v.get(2), ∃(30))

@test
fn test_get_out_of_range_is_none() → ∅:
    let v : mut = [1, 2]
    assert_eq(v.get(2), ∅)
    assert_eq(v.get(99), ∅)

@test
fn test_get_on_empty() → ∅:
    let v : mut = []
    assert_eq(v.get(0), ∅)

// The optional composes with ?? to supply a default.
@test
fn test_get_with_default() → ∅:
    let v : mut = [1, 2]
    assert_eq(v.get(0) ?? ⁻1, 1)
    assert_eq(v.get(9) ?? ⁻1, ⁻1)

// The result in a boolean context tests presence, not truth: an element
// of 0 is a value that is there.
@test
fn test_get_presence_not_truth() → ∅:
    let v : mut = [0]
    let present : mut = false
    if v.get(0):
        present ← true
    assert(present)
    let absent : mut = false
    if v.get(9):
        absent ← true
    assert(¬absent)

@test
fn test_pop_presence_not_truth() → ∅:
    let v : mut = [0]
    let present : mut = false
    if v.pop():
        present ← true
    assert(present)
    let absent : mut = false
    if v.pop():
        absent ← true
    assert(¬absent)

// Unlike get, a subscript out of range is still an error.
@expect error "out of range"
fn error_subscript_still_checks() → ∅:
    let v : mut = [1, 2]
    _ ← v[9]

// ---------------------------------------------------------------------
// Indices that name no element are a mistake, not an outcome
// ---------------------------------------------------------------------

@expect error "insert index 5 out of range"
fn error_insert_past_end() → ∅:
    let v : mut = [1, 2]
    v.insert(5, 9)

@expect error "remove index 5 out of range"
fn error_remove_past_end() → ∅:
    let v : mut = [1, 2]
    _ ← v.remove(5)

@expect error "remove index 0 out of range"
fn error_remove_from_empty() → ∅:
    let v : mut = []
    _ ← v.remove(0)

// ---------------------------------------------------------------------
// Argument counts and element types
// ---------------------------------------------------------------------

@expect error "array.push takes 1 argument"
fn error_push_two_values() → ∅:
    let v : mut = [1]
    v.push(1, 2)

@expect error "array.pop takes 0 arguments"
fn error_pop_with_argument() → ∅:
    let v : mut = [1]
    _ ← v.pop(0)

@expect error "array.insert takes 2 arguments"
fn error_insert_one_argument() → ∅:
    let v : mut = [1]
    v.insert(0)

// A pushed value takes the array's element type, so it can then be read
// back with an index carrying that type's unit.
@test
fn test_push_coerces_to_element_type() → ∅:
    let v : mut = std.bytes("ab")
    v.push(67)
    assert_eq(v.sizeof, 3)
    assert_eq(v.get(2¤byte), ∃(67))

// An index carries the same unit rule as a subscript does.
@test
fn test_index_unit_is_accepted() → ∅:
    let v : mut = std.bytes("abc")
    assert_eq(v.get(1¤byte), ∃(98))

@expect error "array index requires unit"
fn error_index_wrong_unit() → ∅:
    let v : mut = std.bytes("abc")
    _ ← v.get(1¤count)

// ---------------------------------------------------------------------
// The methods compose with the rest of the language
// ---------------------------------------------------------------------

// Building an array by pushing in a loop.
@test
fn test_push_in_a_loop() → ∅:
    let v : mut = []
    foreach i := 1…4:
        v.push(i * i)
    assert_eq(v.sizeof, 4)
    assert_eq(v[0], 1)
    assert_eq(v[3], 16)

// Draining one array into another.
@test
fn test_pop_into_another_array() → ∅:
    let src : mut = [1, 2, 3]
    let dst : mut = []
    foreach i := 1…3:
        dst.push(src.pop() ?? 0)
    assert_eq(src.sizeof, 0)
    assert_eq(dst[0], 3)
    assert_eq(dst[2], 1)

@start
fn main() → ∅:
    std.print("array method tests passed")
