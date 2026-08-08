// Test let bindings: immutability, typed, expressions.

// Basic let definition.
@test
fn test_let_basic() → ∅:
    let x := 42
    assert_eq(x, 42)

// Typed let definition.
@test
fn test_let_typed() → ∅:
    let y : u32 = 100
    assert_eq(y, 100)

// Let binding used in expressions.
@test
fn test_let_in_expr() → ∅:
    let a := 10
    let b := 20
    let c : mut = a + b
    assert_eq(c, 30)

// Let re-binding across loop iterations.
@test
fn test_let_in_loop() → ∅:
    let sum : mut = 0
    foreach i := 1…5:
        let doubled := i * 2
        sum ← sum + doubled
    assert_eq(sum, 30)

// Mutable parameter can be reassigned.
fn increment(x : mut i32) → i32:
    x ← x + 1
    x

@test
fn test_mut_param() → ∅:
    assert_eq(increment(10), 11)

// Immutable parameter cannot be reassigned but value is independent.
fn double_val(x : i32) → i32:
    x * 2

@test
fn test_immutable_param() → ∅:
    let v := 5
    assert_eq(double_val(v), 10)
    assert_eq(v, 5)

// Untyped parameter is also immutable.
fn identity(x) → i32:
    x

@test
fn test_untyped_param_immutable() → ∅:
    assert_eq(identity(7), 7)

@start
fn main() → ∅:
    std.print("let tests passed")

// ---------------------------------------------------------------------
// let protects what a binding names, not only the name
// ---------------------------------------------------------------------
//
// Writing to an element or a field is writing to the thing that holds
// it, so a binding that cannot be reassigned cannot have its parts
// assigned either.

@expect error "cannot assign to element of let variable 'v'"
fn error_element_of_let_array() → ∅:
    let v := [1, 2, 3]
    v[0] ← 9

@expect error "cannot assign to element of let variable 'v'"
fn error_slice_of_let_array() → ∅:
    let v := [1, 2, 3, 4]
    v[1…2] ← [8, 9]

// Reaching through more than one subscript changes nothing: the write
// still lands in what the binding names.
@expect error "cannot assign to element of let variable 'm'"
fn error_nested_element_of_let_array() → ∅:
    let m := [[1, 2], [3, 4]]
    m[0][1] ← 9

let LET_ARRAY := [1, 2, 3]

@expect error "cannot assign to element of let variable 'LET_ARRAY'"
fn error_element_of_let_global() → ∅:
    LET_ARRAY[0] ← 9

// A mutable binding is unaffected.
@test
fn test_element_of_mut_array() → ∅:
    let v : mut = [1, 2, 3]
    v[0] ← 9
    assert_eq(v[0], 9)

@test
fn test_nested_element_of_mut_array() → ∅:
    let m : mut = [[1, 2], [3, 4]]
    m[0][1] ← 9
    assert_eq(m[0][1], 9)

// A parameter is an immutable binding too, so its elements are
// protected until it is declared mut.
fn writes_to_parameter(arr) → ∅:
    arr[0] ← 9

@expect error "cannot assign to element of let variable 'arr'"
fn error_element_of_parameter() → ∅:
    let v : mut = [1, 2]
    writes_to_parameter(v)

// Reading an element is never affected.
@test
fn test_reading_a_let_element() → ∅:
    let v := [1, 2, 3]
    assert_eq(v[0], 1)
    assert_eq(v.get(2), 3)
    let total : mut = 0
    foreach x := v:
        total ← total + x
    assert_eq(total, 6)

// ---------------------------------------------------------------------
// & lends for reading, &mut for writing
// ---------------------------------------------------------------------
//
// A shared borrow says where the value lives, not that the callee may
// change it.  Only mut grants that, whether the value arrived by value
// or by reference.

fn reads_shared(arr : &i32[]) → i32:
    arr[0] + arr[1]

@test
fn test_shared_borrow_reads() → ∅:
    let a : mut i32[] = [10, 20]
    assert_eq(reads_shared(&a), 30)

fn writes_shared(arr : &i32[]) → ∅:
    arr[0] = 99

@expect error "cannot assign to element of borrowed variable 'arr'"
fn error_write_through_shared_borrow() → ∅:
    let a : mut i32[] = [10, 20]
    writes_shared(&a)

fn rebinds_shared(arr : &i32[]) → ∅:
    arr ← [1, 2]

@expect error "cannot assign to borrowed variable 'arr'"
fn error_rebind_shared_borrow() → ∅:
    let a : mut i32[] = [10, 20]
    rebinds_shared(&a)

fn writes_exclusive(arr : &mut i32[], val : i32) → ∅:
    arr[0] = val

// &mut writes through to the caller's array, which is the point of it.
@test
fn test_exclusive_borrow_writes() → ∅:
    let a : mut i32[] = [10, 20]
    writes_exclusive(&a, 99)
    assert_eq(a[0], 99)
    assert_eq(a[1], 20)

// ---------------------------------------------------------------------
// A view carries the access it was built from
// ---------------------------------------------------------------------
//
// A reshape shares the storage it was built from, so binding one as mut
// hands out write access to that storage.  The binding is where this is
// caught: once the view exists it is a mutable local of its own, and a
// write through it says nothing about where its storage came from.

fn mut_view_of_shared(arr : &i32[]) → ∅:
    let m : mut = (2, 2) ⍴ arr
    m[0, 1] = 42

@expect error "cannot take a mutable view of borrowed variable 'arr'"
fn error_mut_view_of_shared_borrow() → ∅:
    let a : mut i32[] = 4 ⍴ 0
    mut_view_of_shared(&a)

fn mut_view_of_immutable_param(arr : i32[]) → ∅:
    let m : mut = (2, 2) ⍴ arr
    m[0, 1] = 42

@expect error "cannot take a mutable view of let variable 'arr'"
fn error_mut_view_of_immutable_parameter() → ∅:
    let a : mut i32[] = 4 ⍴ 0
    mut_view_of_immutable_param(a)

@expect error "cannot take a mutable view of let variable 'a'"
fn error_mut_view_of_let_local() → ∅:
    let a : i32[] = 4 ⍴ 0
    let m : mut = (2, 2) ⍴ a

// A read-only view of something lent for reading is fine.
fn reads_through_a_view(arr : &i32[]) → i32:
    let m := (2, 2) ⍴ arr
    m[0, 0]

@test
fn test_shared_view_of_shared_borrow() → ∅:
    let a : mut i32[] = 4 ⍴ 7
    assert_eq(reads_through_a_view(&a), 7)

// And a mutable view of something lent for writing is fine, and reaches
// the caller.
fn writes_through_a_view(arr : &mut i32[]) → ∅:
    let m : mut = (2, 2) ⍴ arr
    m[0, 1] = 42

@test
fn test_mut_view_of_exclusive_borrow() → ∅:
    let a : mut i32[] = 4 ⍴ 0
    writes_through_a_view(&a)
    assert_eq(a[1], 42)
