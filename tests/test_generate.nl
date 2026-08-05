// test_generate.nl — tests for the generate function

// Basic: generate with lambda over a range
@test
fn test_generate_basic:
  var arr = generate(λx: x * 2, 1…5)
  assert_eq(5, arr.sizeof)
  assert_eq(2, arr[0])
  assert_eq(4, arr[1])
  assert_eq(6, arr[2])
  assert_eq(8, arr[3])
  assert_eq(10, arr[4])

// Generate with a named function
fn square x: i32 -> i32:
  x * x

@test
fn test_generate_named_func:
  var arr = generate(square, 1…4)
  assert_eq(4, arr.sizeof)
  assert_eq(1, arr[0])
  assert_eq(4, arr[1])
  assert_eq(9, arr[2])
  assert_eq(16, arr[3])

// Generate with a curried function
fn multiply a: i32, b: i32 -> i32:
  a * b

@test
fn test_generate_curried:
  var arr = generate(multiply(3), 1…5)
  assert_eq(5, arr.sizeof)
  assert_eq(3, arr[0])
  assert_eq(6, arr[1])
  assert_eq(9, arr[2])
  assert_eq(12, arr[3])
  assert_eq(15, arr[4])

// Generate with a stepped range
@test
fn test_generate_stepped:
  var arr = generate(λx: x, 0…2…10)
  assert_eq(6, arr.sizeof)
  assert_eq(0, arr[0])
  assert_eq(2, arr[1])
  assert_eq(4, arr[2])
  assert_eq(6, arr[3])
  assert_eq(8, arr[4])
  assert_eq(10, arr[5])

// Generate with descending range
@test
fn test_generate_descending:
  var arr = generate(λx: x * x, 3…1)
  assert_eq(3, arr.sizeof)
  assert_eq(9, arr[0])
  assert_eq(4, arr[1])
  assert_eq(1, arr[2])

// Generate with capture in lambda
@test
fn test_generate_capture:
  var offset = 100
  var arr = generate(λx |offset|: x + offset, 1…3)
  assert_eq(3, arr.sizeof)
  assert_eq(101, arr[0])
  assert_eq(102, arr[1])
  assert_eq(103, arr[2])

// Generate with single-element range
@test
fn test_generate_single:
  var arr = generate(λx: x, 5…5)
  assert_eq(1, arr.sizeof)
  assert_eq(5, arr[0])

// Generate result can be iterated with foreach
@test
fn test_generate_foreach:
  var arr = generate(λx: x * 10, 1…3)
  var sum = 0
  foreach v = arr:
    sum ← sum + v
  assert_eq(60, sum)

// Generate result can be subscripted and sliced
@test
fn test_generate_slice:
  var arr = generate(λx: x, 1…10)
  var sub = arr[2…4]
  assert_eq(3, sub.sizeof)
  assert_eq(3, sub[0])
  assert_eq(4, sub[1])
  assert_eq(5, sub[2])

// Error: function returns ∅
@test
@expect error "must not return"
fn test_generate_none_error:
  generate(λx: ∅, 1…3)

// Error: second argument not a range
@test
@expect error "must be a range"
fn test_generate_not_range:
  generate(λx: x, 42)

// Range as first-class value
@test
fn test_range_value:
  var r = 1…5
  var arr = generate(λx: x + 1, r)
  assert_eq(5, arr.sizeof)
  assert_eq(2, arr[0])
  assert_eq(6, arr[4])

// Range in foreach via variable
@test
fn test_range_foreach:
  var r = 1…4
  var sum = 0
  foreach i = r:
    sum ← sum + i
  assert_eq(10, sum)

@start
fn main:
  0
