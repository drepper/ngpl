To Do List: The Compiler, the Runtime, and the Tooling
=====================================================

Work on all the issues without the checkmark.  Implement them on separate git branches.  Always
add test cases and adjust the language specification.  Once a to do item is complete add the
checkmark, commit the change, and change back to main.

This list holds everything that is neither the language nor the bootstrap: ahead-of-time
compilation, the code that is generated, the runtime that code runs against, the object files it
is stored in, and the tools built around all of it.  None of it exists yet, the bootstrap
interpreter standing in for all of it today.  The language is in
[TODO-language.md](TODO-language.md) and the interpreter in
[TODO-bootstrap.md](TODO-bootstrap.md).

A language feature the bootstrap does not have yet is tagged `[FULL]`, one that is half in `[~]`;
the boundary is described in [TODO-bootstrap.md](TODO-bootstrap.md).


The Compiler
------------

[ ] [FULL] compiler mode: ahead-of-time compilation to native code.  Startup function designation
    via command line or attribute.

    Attempt 2 of the self-hosted compiler lives in src/ (src/DESIGN.md, src/ngplc.ngpl,
    src/ANALYSIS.md; attempt 1 archived under old/attempt1/): it compiles the core-1
    subset -- the sized integer family with faithful overflow/wrap semantics, ¤ptrdiff and
    ¤byte units, arrays with borrows, strings, globals, contracts, std.implementation --
    to static syscall-only x86-64 ELF executables, under the control-flow policy: cmov
    selection, eager and/or where speculation is legal, jump tables for dense dispatch,
    aborts as cold out-of-line exits.  tests/run_tests.sh is the one suite; its shared
    phase runs each program through the interpreter and the binary and diffs.  What is
    missing for self-hosting is laid out in src/ANALYSIS.md.

[ ] [FULL] multi-file compilation: compiler accepts multiple source files, build function determines
    compilation strategy.

[ ] [FULL] built-in build system: @build-annotated comptime function provides build recipe.
    Recompiled when source changes.  SBOM generation in output binary.

[ ] what a violation does is always an error.  C++26 chooses between ignore, observe, enforce
    and quick-enforce at build time, which wants a build system to choose in.

    The interpreter now chooses this with `--contracts=ignore|observe|enforce|quick-enforce`; what
    is left is choosing it in a build, and saying what a build's choice does to a library
    compiled under a different one.

[ ] the compiler is fast enough to sit inside an edit-eval-check loop that a program drives.
    That means starting quickly, parsing functions in parallel -- which the context-free grammar
    is what buys -- compiling them in parallel, linking in parallel, and deferring work until
    something asks for it.  A design that is correct and serial is not a design that answers the
    brief.

[ ] a bootstrap of the self-hosted compiler: the compiler is written in the language, the Python
    interpreter runs it, and what it produces takes over.  Deciding what the handover looks like
    -- which artefacts are kept, how a rebuild is checked against the previous stage -- is part
    of this.


Code Generation
---------------

[ ] [FULL] Vulkan code generation for GPU offloading of vector/matrix/tensor operations.

[ ] two ways of translating a function that reads a vector or a matrix, and a rule for choosing
    between them: computed access at O(1) assuming a dense representation and a cache to reward
    it, or iterators and iterator arithmetic, which a compacted or sparse representation needs.
    What a type says about itself -- diagonal, upper or lower triangle, sparse, list-backed --
    feeds the choice and can remove work outright.

[ ] an estimate of the overhead the generated code carries, per piece of source, and per
    instantiation where a function is generic.  It is what tells a programmer or an agent where
    to spend effort, and it is only useful if it is emitted for every instantiation rather than
    for the function once.

[ ] consistent work-splitting for an operation that is parallelized but not associative.  The
    brief requires the result to be the same however many contexts ran it, which makes the split
    part of the semantics rather than of the schedule.  (The memory-model item in
    TODO-language.md is the other half of this.)


Object Files and Linking
------------------------

[ ] [FULL] object file format: possibly custom format supporting partial recompilation.
    Dynamic linking support for system libraries (e.g., Vulkan shared objects).

[ ] the encoding of a type in an object file covers everything a definition says: the members,
    their order, their types, their names, the alignment, and whatever a `@repr` asked for.  Two
    equivalent definitions must encode identically and two differing ones must not, since
    recompiling a source with two same-typed members exchanged is a different program.  A hash
    over the details beside the name is enough to carry it.

[ ] a limited dynamic linker, so a program can call into a system shared object -- Vulkan is the
    first -- together with whatever simulated basic runtime that requires.  The object file
    format need not be the platform's; if it is, partial recompilation has to keep working.

[ ] everything the compiler and the interpreter generate is written under a build directory, by
    default `build/` in the current directory, so a source tree is not written into and a build
    can be thrown away by removing one directory.


Runtime
-------

[ ] [FULL] native runtime using kernel interfaces directly (no libc dependency).  io_uring-based
    async I/O on Linux.

[ ] [FULL] concurrency via clone3 and futex on Linux.

[ ] [FULL] minimal runtime initialization: only pull in code for features actually used.

[ ] a minimal set of OS functions for an embedded target, imported from whatever embedded OS is
    there, so the same runtime story holds where there is no Linux underneath.

[ ] the program's code lives in an address space of its own, not writable and possibly not
    readable, with only the references needed to execute it.  (The address-space item in
    TODO-language.md is what this implements.)


Tooling
-------

[ ] [FULL] JIT compilation in interpreter: background compilation of hot functions, transparent
    switchover.  REPL commands to inspect generated code, machine code, and parse trees.

[ ] [FULL] language server protocol (LSP) mode: expose type information, optimization decisions,
    diagnostics, and code navigation.

[ ] every output the compiler and the interpreter produce is available in a machine-readable form
    beside the human-readable one: the diagnostics, the decisions taken during optimization and
    code generation, the estimates above.  The brief's reason is that the edit-eval-check loop
    may be driven by a program, and a program should not be parsing prose.

[ ] all decision making and analysis details can be requested through log files.  In the final
    compiler version these details are also available through services like LSP.
