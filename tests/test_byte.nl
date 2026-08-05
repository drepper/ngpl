fn sum_bytes data : byte[] -> int:
    var total := 0
    foreach b = data:
        total ← total + b
    total

@test
fn test_byte_array -> ø:
    var data := std.bytes("abc")
    assert_eq(sum_bytes(data), 294)

@test
fn test_byte_sizeof -> ø:
    var data := std.bytes("hello")
    assert_eq(data.sizeof, 5)

@start
fn main -> ø:
    std.print("byte tests passed")
