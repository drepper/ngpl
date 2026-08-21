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
    src/emit.ngpl          # the buffer every backend writes its code into
    src/sha256.ngpl        # the digest a bill of materials names things by
    src/symbols.ngpl       # what a function is called in the object file
    src/sbom.ngpl          # what a program was built from, and its digests
    src/elf.ngpl           # targets, the ELF structures, and writing them
    src/codegen.ngpl       # the x86-64 pipeline, put together
    src/main.ngpl          # the driver, the command line, the @build recipe

    # x86-64 is the pioneer and carries its own of everything: its
    # emitter is hand-tuned and its runtime is machine code written out.
    src/arch_x86_64.ngpl   # x86-64: the emitter
    src/rt_x86_64.ngpl     # x86-64: the runtime, as machine code

    # The other five share one of everything.  Each names only how it
    # spells the abstract operations; there is no rt_aarch64.ngpl
    # because there is no aarch64 runtime -- rt_portable.ngpl is the one
    # runtime the five have between them.
    src/arch_a64.ngpl      # the abstract machine, and aarch64's spellings
    src/dispatch.ngpl      # each abstract operation, dispatched on the target
    src/arch_rv64.ngpl     # riscv64's spellings
    src/arch_i386.ngpl     # i386's
    src/arch_arm.ngpl      # arm's, 32-bit EABI
    src/arch_rv32.ngpl     # riscv32's
    src/tdriver.ngpl       # every IR op composed from those, once
    src/rt_portable.ngpl   # the runtime those five share, written as IR
    src/codegen_t.ngpl     # the pipeline for every target but the pioneer
)
