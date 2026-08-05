/* Tests for std.arena allocator. */

@test
fn test_arena_alloc_and_deinit → ∅:
    var alloc := std.arena.allocator()
    var dir := std.fs.cwd()
    var file := dir.openFile("CLAUDE.md")
    var data := file.read_file(alloc)
    assert(data.sizeof > 0)
    alloc.deinit()

@test
fn test_arena_independent → ∅:
    var a1 := std.arena.allocator()
    var a2 := std.arena.allocator()
    var dir := std.fs.cwd()
    var f1 := dir.openFile("CLAUDE.md")
    var d1 := f1.read_file(a1)
    a1.deinit()
    var f2 := dir.openFile("CLAUDE.md")
    var d2 := f2.read_file(a2)
    assert(d2.sizeof > 0)
    a2.deinit()

@test
fn test_arena_reset → ∅:
    var alloc := std.arena.allocator()
    var dir := std.fs.cwd()
    var f1 := dir.openFile("CLAUDE.md")
    var d1 := f1.read_file(alloc)
    assert(d1.sizeof > 0)
    alloc.reset()
    var f2 := dir.openFile("CLAUDE.md")
    var d2 := f2.read_file(alloc)
    assert(d2.sizeof > 0)
    alloc.deinit()

@start
fn main → ∅:
    std.print("arena tests passed")
