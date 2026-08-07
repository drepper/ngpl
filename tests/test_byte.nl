fn sum_bytes(data : byte[]) → int:
    let total : mut = 0
    foreach b := data:
        total ← total + b
    total

@test
fn test_byte_array() → ∅:
    let data : mut = std.bytes("abc")
    assert_eq(sum_bytes(data), 294)

@test
fn test_byte_sizeof() → ∅:
    let data : mut = std.bytes("hello")
    assert_eq(data.sizeof, 5)

@start
fn main() → ∅:
    std.print("byte tests passed")
