// Tests for scope-based release of operating system resources.
//
// A value holding a file descriptor is owned by the binding it was
// assigned to.  When that binding's scope ends the descriptor is
// released, and the value becomes unavailable.  close() does the same
// thing early.

// ---------------------------------------------------------------------
// Scope end releases the descriptor
// ---------------------------------------------------------------------

fn opens_and_drops() → ∅:
    let dir : mut = std.fs.cwd()
    let file : mut = dir.open_file("CLAUDE.md")
    _ ← file.fd

// Descriptors are reused once released, so a leak would make the number
// climb with every call.  Two hundred iterations would exhaust a typical
// limit if nothing were being closed.
@test
fn test_scope_end_releases_descriptors() → ∅:
    foreach i := 1…200:
        opens_and_drops()
    let dir : mut = std.fs.cwd()
    let file : mut = dir.open_file("CLAUDE.md")
    assert(file.fd < 50)

// ---------------------------------------------------------------------
// A returned resource escapes its defining scope
// ---------------------------------------------------------------------

fn make_file():
    let dir : mut = std.fs.cwd()
    dir.open_file("CLAUDE.md")

// Ownership passes to the caller, so the file is still open.
@test
fn test_returned_file_survives() → ∅:
    let alloc : mut = std.arena.allocator()
    let file : mut = make_file()
    assert(¬file.is_closed)
    let data : mut = file.read_file(alloc)
    assert(data.sizeof > 0)
    alloc.deinit()

// ---------------------------------------------------------------------
// A parameter is borrowed, not owned
// ---------------------------------------------------------------------

fn borrows(f) → bool:
    f.is_closed

// The callee's scope ending must not close the caller's file.
@test
fn test_parameter_is_not_destroyed() → ∅:
    let dir : mut = std.fs.cwd()
    let file : mut = dir.open_file("CLAUDE.md")
    assert(¬borrows(file))
    assert(¬file.is_closed)
    _ ← file.fd

// ---------------------------------------------------------------------
// close() releases early and makes the value unavailable
// ---------------------------------------------------------------------

@test
fn test_close_marks_closed() → ∅:
    let dir : mut = std.fs.cwd()
    let file : mut = dir.open_file("CLAUDE.md")
    assert(¬file.is_closed)
    file.close()
    assert(file.is_closed)

// Closing early and then letting the scope end is not a double release.
@test
fn test_close_then_scope_end() → ∅:
    let dir : mut = std.fs.cwd()
    let file : mut = dir.open_file("CLAUDE.md")
    file.close()

@expect error "fd: file is closed"
fn error_fd_after_close() → ∅:
    let dir : mut = std.fs.cwd()
    let file : mut = dir.open_file("CLAUDE.md")
    file.close()
    _ ← file.fd

@expect error "read_file: file is closed"
fn error_read_after_close() → ∅:
    let alloc : mut = std.arena.allocator()
    let dir : mut = std.fs.cwd()
    let file : mut = dir.open_file("CLAUDE.md")
    file.close()
    _ ← file.read_file(alloc)

@expect error "close: file is closed"
fn error_double_close() → ∅:
    let dir : mut = std.fs.cwd()
    let file : mut = dir.open_file("CLAUDE.md")
    file.close()
    file.close()

// ---------------------------------------------------------------------
// Directories hold a descriptor too
// ---------------------------------------------------------------------

@test
fn test_dir_close_marks_closed() → ∅:
    let dir : mut = std.fs.cwd()
    assert(¬dir.is_closed)
    dir.close()
    assert(dir.is_closed)

@expect error "open_file: directory is closed"
fn error_open_on_closed_dir() → ∅:
    let dir : mut = std.fs.cwd()
    dir.close()
    _ ← dir.open_file("CLAUDE.md")

@expect error "close: directory is closed"
fn error_double_close_dir() → ∅:
    let dir : mut = std.fs.cwd()
    dir.close()
    dir.close()

@start
fn main() → ∅:
    std.print("scope close tests passed")
