# The compiler's own sources, in the order they are compiled.
#
# The order is part of the program, not a convenience.  A struct may be
# declared below whatever names it -- the parser sweeps the token stream
# for struct names before it parses anything -- but an `enum` and a
# `unit` are registered as they are read, so `elf.ngpl` must come after
# nothing in particular but before nobody, and every file that writes
# `Sht` or `¤"shndx"` must come after the file that declares them.
#
# For the same reason nothing here may glob `src/*.ngpl`: alphabetical
# order is not the order the program is in.
#
# The same list is written in the @build recipe in src/main.ngpl, and
# the two are checked against each other by the bootstrap comparing
# stage 1 (built from this list) against stage 2 (built from the
# recipe).  If they ever disagree, the bootstrap says so.
NGPLC_SOURCES=(
    src/tokens.ngpl        # token kinds, byte-run helpers
    src/types.ngpl         # type codes and the helpers over them
    src/diag.ngpl          # a diagnostic, and which file a line came from
    src/lex.ngpl           # the byte-class table and the scan it drives
    src/ast.ngpl           # node kinds and the flat parallel arrays
    src/parse.ngpl         # tokens → Ast
    src/dumpast.ngpl       # --dump-ast
    src/check.ngpl         # names, types, widths, units, mutability, purity
    src/comptime.ngpl      # running the @build recipe while building
    src/ir.ngpl            # the three-address IR
    src/lower.ngpl         # Ast + Chk → IrFn
    src/x86.ngpl           # the x86-64 pioneer: emitter and runtime
    src/symbols.ngpl       # what a function is called in the object file
    src/elf.ngpl           # targets, the ELF structures, and writing them
    src/codegen.ngpl       # the x86-64 pipeline, put together
    src/main.ngpl          # the driver, the command line, the @build recipe
    src/arch_a64.ngpl      # the abstract machine, and aarch64
    src/dispatch.ngpl      # every abstract operation, dispatched on target
    src/arch_rv64.ngpl     # riscv64
    src/arch_i386.ngpl     # i386
    src/arch_arm.ngpl      # arm, 32-bit EABI
    src/arch_rv32.ngpl     # riscv32
    src/tdriver.ngpl       # every IR op composed from the abstract ops
    src/rt_ir.ngpl         # the runtime, written once as IR
    src/codegen_t.ngpl     # the pipeline for every target but the pioneer
)
