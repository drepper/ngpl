// std.exit terminates at once with the given status: the line after it
// never runs, and the @start function's own return value is not used.

fn quit_early() → ∅:
    std.print("quitting")
    std.exit(42)
    std.print("unreachable")

@start
fn main() → u8:
    quit_early()
    std.print("also unreachable")
    0
