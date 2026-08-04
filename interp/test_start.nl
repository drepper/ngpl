/* Hash and display CLAUDE.md using the newlang runtime */
@start
fn main() -> none {
    var dir = std.fs.cwd();
    var file = dir.openFile("CLAUDE.md");
    var data = file.read_file(std.heap.allocator());
    var hash = std.sha256(data);
    var filename = "  CLAUDE.md";
    std.print(hash, filename);
}
