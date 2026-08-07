// Only layouts the implementation actually defines are accepted.

@repr(Rust)
struct Header:
    magic : u32

@start
fn main() → ∅:
    std.print(Header.sizeof)
