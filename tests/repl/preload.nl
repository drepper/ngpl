// Fixture for the REPL preload tests: definitions the session inherits.

fn triple(n : int) → int:
    n × 3

let LIMIT := 99

@start
fn main() → ∅:
    std.print("main should not run under --repl")
