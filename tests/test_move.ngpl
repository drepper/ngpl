// Tests for move semantics: consuming self invalidates the caller's variable.

struct Bag:
    items: int
    label: str

impl Bag:
    fn new(n: int, label: str) -> Bag:
        Bag { items: n, label: label }

    fn peek(&self) -> int:
        self.items

    fn take(self) -> int:
        self.items

// Consuming method works and returns the value.
@test
fn test_consume_ok() → ∅:
    let b := Bag.new(5, "fruit")
    let n := b.take()
    assert_eq(n, 5)

// Error: field access after consuming method.
@test
@expect error "moved"
fn test_field_after_consume() → ∅:
    let b := Bag.new(5, "fruit")
    let n := b.take()
    assert_eq(b.items, 5)

// Error: method call after consuming method.
@test
@expect error "moved"
fn test_method_after_consume() → ∅:
    let b := Bag.new(5, "fruit")
    b.take()
    b.peek()

// Borrowing method does not consume.
@test
fn test_borrow_survives() → ∅:
    let b := Bag.new(7, "tools")
    let a := b.peek()
    let c := b.peek()
    assert_eq(a, 7)
    assert_eq(c, 7)

// Reassignment after consume restores the variable.
@test
fn test_reassign_after_consume() → ∅:
    let b : mut = Bag.new(1, "a")
    let n := b.take()
    assert_eq(n, 1)
    b ← Bag.new(2, "b")
    assert_eq(b.peek(), 2)

@start
fn main() → ∅:
    std.print("move tests passed")
