// Tests for std.callstack and the argument checking of std.exit and
// std.abort.
//
// The termination behaviour of exit and abort cannot be tested from
// inside a test -- terminating would end the test run -- so the process
// exit statuses are checked by the output tests exit_code, exit_range,
// abort_default, abort_signal, and abort_invalid, and the automatic
// backtrace by the output test backtrace.

// ---------------------------------------------------------------------
// std.callstack
// ---------------------------------------------------------------------

// Each entry is a (name, line, column) tuple.
@test
fn test_frame_shape() → ∅:
    let frames : mut = std.callstack()
    let top : mut = frames[0]
    assert_eq(top[0], "test_frame_shape")
    assert(top[1] > 0)

// Entry 0 is the function that asked, not callstack itself.
@test
fn test_innermost_is_caller() → ∅:
    assert_eq(std.callstack()[0][0], "test_innermost_is_caller")

fn level_one() → str:
    level_two()

fn level_two() → str:
    level_three()

fn level_three() → str:
    let frames : mut = std.callstack()
    frames[0][0]

// A function three levels down still names itself at entry 0.
@test
fn test_names_own_frame() → ∅:
    assert_eq(level_one(), "level_three")

// The callers appear after it, outward in order.
fn check_chain() → bool:
    let frames : mut = std.callstack()
    assert_eq(frames[0][0], "check_chain")
    assert_eq(frames[1][0], "outer_of_chain")
    assert_eq(frames[2][0], "test_chain_order")
    true

fn outer_of_chain() → bool:
    check_chain()

@test
fn test_chain_order() → ∅:
    assert(outer_of_chain())

// The stack grows and shrinks with the calls it describes.
fn depth() → int:
    let frames : mut = std.callstack()
    frames.sizeof

fn depth_plus_one() → int:
    depth()

@test
fn test_depth_grows_with_nesting() → ∅:
    assert_eq(depth_plus_one(), depth() + 1)

@expect error "takes no arguments"
fn error_callstack_with_argument() → ∅:
    let frames : mut = std.callstack(1)

// ---------------------------------------------------------------------
// std.exit argument checking
// ---------------------------------------------------------------------

@expect error "outside the range"
fn error_exit_code_too_large() → ∅:
    std.exit(256)

@expect error "outside the range"
fn error_exit_code_negative() → ∅:
    std.exit(⁻1)

@expect error "must be an integer"
fn error_exit_code_not_an_integer() → ∅:
    std.exit("42")

// ---------------------------------------------------------------------
// std.abort argument checking
// ---------------------------------------------------------------------

@expect error "must be an integer"
fn error_abort_signal_not_an_integer() → ∅:
    std.abort("SIGTERM")

@start
fn main() → ∅:
    std.print("callstack tests passed")
