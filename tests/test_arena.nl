// Tests for std.arena allocator.

@test
fn test_arena_alloc_and_deinit() → ∅:
    let alloc : mut = std.arena.allocator()
    let dir : mut = std.fs.cwd()
    let file : mut = dir.open_file("CLAUDE.md")
    let data : mut = file.read_file(alloc)
    assert(data.sizeof > 0)
    alloc.deinit()

@test
fn test_arena_independent() → ∅:
    let a1 : mut = std.arena.allocator()
    let a2 : mut = std.arena.allocator()
    let dir : mut = std.fs.cwd()
    let f1 : mut = dir.open_file("CLAUDE.md")
    let d1 : mut = f1.read_file(a1)
    a1.deinit()
    let f2 : mut = dir.open_file("CLAUDE.md")
    let d2 : mut = f2.read_file(a2)
    assert(d2.sizeof > 0)
    a2.deinit()

@test
fn test_arena_reset() → ∅:
    let alloc : mut = std.arena.allocator()
    let dir : mut = std.fs.cwd()
    let f1 : mut = dir.open_file("CLAUDE.md")
    let d1 : mut = f1.read_file(alloc)
    assert(d1.sizeof > 0)
    alloc.reset()
    let f2 : mut = dir.open_file("CLAUDE.md")
    let d2 : mut = f2.read_file(alloc)
    assert(d2.sizeof > 0)
    alloc.deinit()

@start
fn main() → ∅:
    std.print("arena tests passed")
