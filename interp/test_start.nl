/* Hash and display CLAUDE.md using the newlang runtime */
@start
fn main() -> none {
    var dir = fs.cwd();
    var file = dir.openFile("CLAUDE.md");
    var data = file.read_file(heap.allocator());
    var hash = sha256(data);
    var combined = format(hash) + "  CLAUDE.md";
    format(combined, get_stdout().fd);
}
