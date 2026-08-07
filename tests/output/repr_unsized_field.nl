// A @repr(C) struct cannot hold an arbitrary-precision field: there is
// no C type to match it to.  The error names the field, not just the
// struct, and points at the sized type to use instead.

@repr(C)
struct Header:
    magic : u32
    length : int

@start
fn main() → ∅:
    std.print(Header.sizeof)
