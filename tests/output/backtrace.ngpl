// An error raised several calls deep reports the whole chain, innermost
// first, naming only the program's own functions.

fn innermost(n : int) → int:
    let values := [1, 2]
    values[n]

fn middle(n : int) → int:
    innermost(n) + 1

fn outer(n : int) → int:
    middle(n) × 2

@start
fn main() → ∅:
    std.print("before")
    std.print(outer(9))
