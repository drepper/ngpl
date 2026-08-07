// Tests for compile-time @ introspection on parameters and loop variables.

// --- @typeof on function parameters ---

fn ret_i32() → i32:
    0

fn typeof_param(x : i32) → ∅:
    static_assert_eq(@typeof(x), @resultof(ret_i32))

@test
fn test_typeof_param() → ∅:
    typeof_param(42)

fn typeof_str_param(s : str) → ∅:
    static_assert_eq(@typeof(s), @typeof(""))

@test
fn test_typeof_str_param() → ∅:
    typeof_str_param("hello")

fn typeof_bool_param(b : bool) → ∅:
    static_assert_eq(@typeof(b), @typeof(true))

@test
fn test_typeof_bool_param() → ∅:
    typeof_bool_param(false)

fn typeof_array_param(arr : i32[]) → ∅:
    static_assert_eq(@typeof(arr), @typeof([1]))

@test
fn test_typeof_array_param() → ∅:
    let a : mut i32[] = [1, 2, 3]
    typeof_array_param(a)

// --- @typeof on foreach loop variables ---

@test
fn test_typeof_foreach_range() → ∅:
    foreach i := 1…3:
        static_assert_eq(@typeof(i), @typeof(0))

@test
fn test_typeof_foreach_array() → ∅:
    let arr : mut = [10, 20, 30]
    foreach v := arr:
        static_assert_eq(@typeof(v), @typeof(0))

// --- @unitof on function parameters ---

fn unitof_param(d ¤meter : int) → ∅:
    static_assert_eq(@unitof(d), ¤meter)

@test
fn test_unitof_param() → ∅:
    unitof_param(100 ¤meter)

// --- @unitof on foreach loop variables ---

@test
fn test_unitof_foreach_range() → ∅:
    foreach off := 0 ¤byte…3 ¤byte:
        static_assert_eq(@unitof(off), ¤byte)

@test
fn test_unitof_foreach_stepped() → ∅:
    let total ¤byte : mut = 128
    foreach off := 0…64…(total - 1):
        static_assert_eq(@unitof(off), ¤byte)

// --- @sizeof on parameter packs ---

fn sizeof_pack_param(args…) → int:
    @sizeof(args)

@test
fn test_sizeof_pack_param() → ∅:
    assert_eq(sizeof_pack_param(1, 2, 3), 3)
    assert_eq(sizeof_pack_param(), 0)

// --- @typeof in comptime foreach ---

fn comptime_typeof(args…) → int:
    let count : mut int = 0
    comptime foreach v := args:
        if @typeof(v) == @typeof(0):
            count ← count + 1
    count

@test
fn test_typeof_comptime_foreach() → ∅:
    assert_eq(comptime_typeof(1, "a", 2), 2)

// --- error: @typeof on non-comptime variable ---

@test
@expect error "compile-time constant"
fn test_typeof_runtime_var() → ∅:
    let x : mut = 42
    @typeof(x)

// --- error: @sizeof on runtime array variable ---

@test
@expect error "compile-time constant"
fn test_sizeof_runtime_var() → ∅:
    let arr : mut = [1, 2, 3]
    @sizeof(arr)

// --- error: @unitof on runtime variable ---

@test
@expect error "compile-time constant"
fn test_unitof_runtime_var() → ∅:
    let d ¤meter : mut = 5
    @unitof(d)

@start
fn main() → ∅:
    std.print("comptime introspection tests passed")
