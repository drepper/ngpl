// Tests for function purity.
//
// Functions are pure by default: they may only depend on their parameters
// and locally defined variables.  Reading or writing mutable global
// variables from a pure function is an error.
//
// The @impure annotation lifts this restriction.

let counter : mut = 0
let LIMIT := 100

// Pure function assigning to a local variable is fine.
@test
fn test_pure_local_assign() → ∅:
    let x : mut = 0
    x ← 42
    assert_eq(x, 42)

// Pure function cannot assign to a mutable global.
@test
@expect error "pure function.*cannot assign to non-local"
fn test_pure_rejects_global_write() → ∅:
    counter ← 1

// Pure function cannot read a mutable global.
@test
@expect error "pure function.*cannot read mutable global"
fn test_pure_rejects_global_read() → ∅:
    let x : mut = counter

// Pure function CAN read a constant.
@test
fn test_pure_reads_const() → ∅:
    assert_eq(LIMIT, 100)

// Pure function CAN call other functions.
fn double(x : int) → int:
    x * 2

@test
fn test_pure_calls_function() → ∅:
    assert_eq(double(3), 6)

// An @impure function CAN read and write mutable globals.
@impure
fn bump_counter() → ∅:
    counter ← counter + 1

@impure
fn get_counter() → int:
    counter

@test
fn test_impure_allows_global_access() → ∅:
    bump_counter()
    assert_eq(get_counter(), 1)

// Pure function calling an impure function is allowed —
// the impure callee handles the side effect.
@test
fn test_pure_calls_impure() → ∅:
    bump_counter()
    assert_eq(get_counter(), 2)

@start
fn main() → ∅:
    std.print("purity tests passed")
