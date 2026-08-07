// test_type_alias.nl -- type alias definitions

type Index = i32
type Vec3 = f64[3]
type Row = i32[]

// --- alias used in variable definition ------------------------------------

@test
fn test_alias_var_def() → ∅:
  let x : Index = 42
  assert_eq(x, 42)

// --- alias used in function parameter -------------------------------------

fn add_indices(a : Index, b : Index) → Index:
  a + b

@test
fn test_alias_param() → ∅:
  assert_eq(add_indices(10, 20), 30)

// --- alias for fixed-size array -------------------------------------------

@test
fn test_alias_fixed_array() → ∅:
  let v : Vec3 = [1.0, 2.0, 3.0]
  assert_eq(v[0], 1.0)
  assert_eq(v[2], 3.0)

// --- alias for dynamic array in parameter ---------------------------------

fn sum_row(r : Row) → i32:
  let total : mut = 0
  foreach i := 0…(r.sizeof - 1):
    total ← total + r[i]
  total

@test
fn test_alias_dynamic_array_param() → ∅:
  let a : mut i32[] = [1, 2, 3, 4]
  assert_eq(sum_row(a), 10)

// --- alias chains (alias of alias) ----------------------------------------

type Offset = Index

fn use_offset(o : Offset) → i32:
  o + 1

@test
fn test_alias_chain() → ∅:
  assert_eq(use_offset(9), 10)

// --- alias in let with mut ------------------------------------------------

@test
fn test_alias_mut_var() → ∅:
  let x : mut Index = 0
  x ← 99
  assert_eq(x, 99)

@start
fn main() → ∅:
  std.print("type alias tests passed")
