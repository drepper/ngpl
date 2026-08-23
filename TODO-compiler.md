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

    Attempt 2 of the self-hosted compiler lives in src/ (src/DESIGN.md, twenty-four .ngpl
    sources listed in build order by build/sources.sh, src/ANALYSIS.md; attempt 1 archived
    under old/attempt1/): it compiles the core-1
    subset -- the sized integer family with faithful overflow/wrap semantics, ¤ptrdiff and
    ¤byte units, arrays with borrows, strings, globals, contracts, std.implementation --
    to static syscall-only x86-64 ELF executables, under the control-flow policy: cmov
    selection, eager and/or where speculation is legal, jump tables for dense dispatch,
    aborts as cold out-of-line exits.  tests/run_tests.sh is the one suite; its shared
    phase runs each program through the interpreter and the binary and diffs.  What is
    missing for self-hosting is laid out in src/ANALYSIS.md.

[x] multi-file compilation: both front ends take several source files and read them as if
    they were one, concatenated in the order named; a diagnostic still says which file and
    which line within it.  A file boundary is a line boundary.  What is not yet true is
    separate compilation: there is one text and one pass over it, so this is the stand-in
    for a module system, not the thing itself.  Note the order of the list is significant --
    an enum and a unit must be declared before use, though a struct need not be.

[x] a type names a measure the file declared: type_name_m() takes the marks and type_name()
    stays the same thing for a caller with no file to ask.  The checker reaches the Ast's marks
    through one method, so its hundred-odd message sites say '¤line' rather than '¤unit#27'.

[x] a literal carries a measure the file declared: '3¤"line"'.  The lexer still settles the
    built-in measures, and now hands anything else back -- the ¤ and the name lex as themselves
    -- for the parser, which by then knows what the file declared, to put on the literal.  This
    is what the interpreter always did, where ¤ is an ordinary operator.

[ ] thirty expectations still match by text.  583 of 613 name their diagnostic by number
    now; the rest are ones that never fired during the sweep that found the raise sites --
    tests/test_float*.ngpl and tests/test_roots.ngpl wait on floats the interpreter does not
    implement, and a few depend on the environment -- so there was no number to read off.
    Each wants the same treatment: make the expectation fire, note which site raised it, give
    that site a number from its block, and let tools/update_expectations.py fill the message.
    Spec: "What a Diagnostic Is Known By".

[ ] a walk is what keeps the object it walks alive, and nothing acts on that yet.  Since
    `foreach x := v: v ← …` is allowed, the object the walk took can lose its last name
    while the walk is still going, and what keeps it whole until the loop ends is the
    walk's own hold on it.  The interpreter already does the right thing, because Python
    counts references and drops the array when the walk lets go.  The compiled runtime
    does nothing, because its allocator is a bump over mmap regions and gives nothing
    back -- so the requirement is met by there being no freeing at all rather than by
    freeing at the right moment.  When an allocator that frees arrives, the end of a walk
    is where a walked object with no name left becomes reclaimable, and the lifetime the
    checker already computes is where that would be read off.  Spec: "Writing the Name Is
    Not Writing the Object".

[ ] the packing analysis does not follow a binding into a call.  A T[] whose length is
    settled and which never leaves the function is laid out as a T[N] is; whether it
    leaves is decided by counting every read of the name against the reads somewhere a
    packed array serves -- an element read, an element write, #, a walk, and the three
    that lay it out afresh anyway: ⧺, a slice, ⍴.  Anything else disqualifies it, which
    is why it is safe.  Being handed to a function is the one left worth having, and the
    one that needs more than a call to pack_safe: the callee would have to be known not
    to keep what it was given, which is an escape question about the callee and not
    about this binding.  Of 162 T[] locals in the compiler's own source 159 are `= []`
    filled by push, so what the analysis finds here is small; it is for programs that are
    not this one.

[ ] more of the compiler's own tables could say their size.  src/lex.ngpl's class table
    did: it was 256 push calls into a T[] and is now `256 ⍴ 0` into an i64[256], which is
    one fill of the caller's own space and a bound every self.cls[b] checks against a
    constant.  A sweep for the rest found targets() (six pushes of a struct) and
    plan_elf's phdrs/shdrs (four each), none of which pack, because a sized array is the
    elements and nothing else only where an element is something a load can move -- see
    farr_is_packed in check.ngpl.  What would make those pay is packing a T[N] of
    @repr(C) structs, which needs a struct value to have a C layout as well as the slot
    layout it has now.

[ ] a sized array stored into a struct field is copied into the struct's own memory, every
    time.  It has to be: the struct outlives the frame.  But where the struct itself
    provably does not outlive the frame the copy is waste, and where the field is built in
    place -- Ident{mag: [127, 69, 76, 70]} -- the elements could be written into the
    struct's memory outright rather than into the frame and then copied.  The second is
    the same "answer into space the caller provides" the return path already does.

[ ] a sized array cannot be handed to a T[] parameter.  The two are laid out differently
    -- a T[N] is its elements packed, a T[] a header and a slot apiece -- so the call would
    have to convert, and ngplc refuses it rather than convert silently.  The interpreter
    allows it, so this is ngplc being the stricter of the two, which is the permitted
    direction; but it means a digest cannot be given to a helper written against u8[], and
    tests/compile/t58_sha256.ngpl had to say u8[32] where it said u8[].  Converting at the
    call, for a by-value or shared parameter only, would cost one lay-out and is worth it
    if this turns out to bite.  A &mut parameter could never take one: writes through the
    conversion would reach nothing.  Spec: "What a Sized Array Is Made Of".

[ ] the hash handle's type does not say which algorithm made it.  digest() has to answer a
    fixed width, and with one algorithm it reads the width from the only entry there is.
    check.ngpl asserts #hash_algs() = 1 at that point, so a second algorithm stops the
    compiler rather than answering the wrong width -- but what it wants is for TY_HASH to
    carry the algorithm, which is a band in the type encoding rather than a bare code.

[ ] ngplc answers for twenty of the numbers.  It checks every @expect definition now and
    holds it to the numbers it names, but only where it draws that number itself --
    diag_codes() in src/check.ngpl is the list, and tests/compile/run_compile_tests.sh
    checks the list against the derrc/dwarn calls.  Everything else ngplc refuses is still
    numberless, so an expectation naming it is passed over rather than checked.  The work is
    the same for each: give the site a number from its block, matching the interpreter's
    number for the same refusal, and add it to diag_codes().  Spec: "What `@expect` Means to
    the Compiler".

[ ] a definition marked @expect error that ngplc does not refuse is not caught.  It is the
    check worth having -- a program the interpreter refuses must not compile -- but a
    compiler cannot tell a diagnostic it is missing from one the interpreter only finds by
    running, and tests/test_reshape.ngpl has five of the latter.  It becomes checkable once
    an expectation can say which of the two it is, or once every compile-time refusal has a
    number and the run-time ones are the remainder.

[ ] an unused string literal reaches .rodata.  The pool comes from the lexer, so every
    literal in the source is emitted whether anything reads it or not -- an @expect message,
    a line in a function nobody calls.  No instruction is generated for either, so this is
    size and not correctness, but the tests carry forty-two @expect messages they have no
    use for.  Emitting only the strings something references fixes both.

[ ] the interpreter cannot always tell a program it refuses from a program that ran and
    stopped.  It checks types as it evaluates, so both arrive at the same place as Python
    exceptions, and the two leave with different statuses: a refusal 1, a stop the reserved
    64.  The ones that are unmistakable carry it -- ContractError, OverflowError,
    ProgramStop, RuntimeError -- and interp/errors.py's ProgramStop is where a stop says it
    is one.  Everything else raised while evaluating is still taken for a refusal, which is
    right for a type error and wrong for, say, an index past the end.  Converting the rest
    is a raise-site-by-raise-site job; each one converted makes another t9N test comparable.
    The compiler has no such trouble: it refuses before it runs.

[ ] arm and riscv32 do not report a stack overflow.  The other four install a SIGSEGV
    handler at startup, on a sigaltstack, and compare the faulting address against the
    guard's bounds; these two cannot, because a handler is entered with the kernel's calling
    convention and they take a routine's arguments on the stack where the kernel puts them
    in registers -- so what the handler would read is whatever the alternate stack happened
    to hold.  x86-64 and i386 pass on the stack (i386 by an accident that lines the kernel's
    three words up with the first argument cell and a half), and the 64-bit machines pass one
    argument to a register, which is why those four manage.  What these two need is a
    trampoline entered by the kernel that puts r0/r1 -- a0/a1 on rv32 -- where the runtime's
    prologue looks for them, and then calls RT_SEGV.  Spec: "The Stack Running Out", where
    the gap is written down.

[ ] a copy at a call, for the types that have none.  By value means a copy, elided
    wherever nothing can change the original during the call -- which is everywhere but a
    &mut of the same binding in the same call.  There the copy is made, and an array of
    numbers, characters or strings is copied by cycling it to its own length (IR_ACYC).
    An array of arrays or of structs would need its elements copied too; a struct needs a
    field-by-field copy; a dictionary needs one at all.  Until those exist the call is
    refused, by both implementations, saying which type it could not copy.  Spec: "By Value
    Is a Copy", where this is written down as a limitation rather than a rule.

[ ] ngplc stops with "index out of range" on `_ ← it.next()` -- an iterator's next()
    discarded rather than bound.  The lowering reaches lower_mcall with a node id of ⁻1
    (src/lower.ngpl:98, through lower_expr_i:521).  The interpreter runs the same program.
    Found while probing the walk-borrow rule; the shape is a discarded method call whose
    result is an optional, so `_ ← v.pop()` is worth trying too.  A crash rather than a
    diagnostic is the worst kind of refusal, so this one is worth a look before the next
    feature.

[ ] std.println's format is written before its arguments are worked out, in a compiled
    program but not under the interpreter.  The compiler puts the literal run of a format down
    as it reaches it and evaluates each {} when it gets there; the interpreter builds the whole
    line and writes it once.  Nothing sees the difference unless an argument stops the
    program -- an abort, a violated contract, a bounds check -- and then the compiled run has
    left the literal prefix on stdout and the interpreted one has not.  tests/compile/
    t95_hash_spent.ngpl was written around it and says so where it does.  Which one is right
    is a question for the spec: writing as you go is what a program that formats a megabyte
    wants, and formatting first is what makes a line atomic.  Whichever it is, both
    implementations should do it.

[ ] the compiler's own refusals have no home in the suite.  tests/compile/ requires every
    program to compile and tests/output/ drives the interpreter, so what ngplc says no to --
    a std.build outside a recipe, a recipe reaching past the subset, two @build functions --
    is checked by hand today.  A tests/compile/refuse/*.ngpl + *.expected pair driven from
    run_compile_tests.sh is the right shape, and the suite will want it for far more than
    @build.

[ ] [FULL] separate compilation: a source file compiled on its own into something the next
    step links, so a change to one file does not re-read the rest.  The module system is
    what decides the unit; until then, multi-file compilation above reads everything.

[x] built-in build system: an @build-annotated comptime-only function provides the build
    recipe; --build FILE finds it, runs it, and compiles what it names.  No code for it is
    written into the executable.  Declares sources, output name, output directory, search
    paths and flags.  Still to do: recompiled-when-source-changes, and SBOM generation in
    the output binary, both of which want separate compilation first.

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

[ ] everything the compiler and the interpreter generate *besides the linked executable* is
    written under a build directory, by default `build/` in the current directory, so a source
    tree is not written into and a build can be thrown away by removing one directory.  The
    executable itself follows the Unix convention instead: `a.out` in the current directory
    unless `-o` names the file -- decided and implemented; this item now covers the
    intermediate artifacts (caches, logs, per-file objects) once they exist.


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

[ ] this depends on a module system being implemented.  make using rt_x86_64.ngpl optional.  add
    a compile option.  implement a mechanism similar to zig ≥ 0.15 std.Build.option to allow
    using -Doption=value on the build command line.  use the portable implementation for x86_64
    by default as well, do not add rt_x86_64.ngpl to the source file list.  the build option,
    perhaps named optimized-runtime, can be repeated, each copy naming one file to be used for
    the runtime selection.  the files must contain a module with a name matching the file name.
    the module must contain a function arch_match which takes a string and returns a bool.  The
    parameter is the name of the architecture the binary is created for and the return value
    indicates whether the optimized functions in the module apply to that architecture.
    The compiler checks for all the needed runtime functions whether it is defined in the module.
    if no optimized runtime is given, the portable rt functions can be called directly.
    Otherwise the optimized routine is emitted.

[x] the compiler creates a hash for all the sources it compiles.  On by default, no flag:
    a token-based digest in src/sbom.ngpl (kind and content, so a comment, a rewrap or -> for
    → does not move it), .sbom and .sbomstr in their own read-only segment, last of what is
    loaded, with rows for the compiler, each source, all the sources, and the program.  The
    program's own digest covers the code, what it reads, what it writes, the entry point, the
    machine and the class -- not the bill, which would be a hash of its own hash, and not the
    name, since the same program deployed twice is one program.  Spec: chapter 8, "The Bill of
    Materials".

    What made it affordable was std.hash: the host's own implementation under the interpreter,
    and the runtime in a compiled program.  SHA-256 written in the language ran at 6 MB/s compiled and 2.4 KiB/s
    interpreted, which would have added forty minutes to stage 1.  The routine is written once
    as IR in src/rt_hash.ngpl and src/rt_sha256.ngpl and compiled by all six targets -- the
    pioneer through emit_fn and the other five through t_emit_fn -- rather than by hand for
    x86-64 and as IR for the rest: it is arithmetic and nothing else, so there is nothing a
    hand-written version would know that the IR does not.  The bill is fed as the tokens are
    read rather than gathered into an array first, which is what std.hash.<alg>.start() is
    for.  Measured: stage 1 is 482 s with the bill and 485 s without, and
    a native self-compile 0.35 s with and 0.22 s without, the difference being the feed the
    digest is taken over rather than the digest.

[ ] the original wording, for what the entry kinds are to grow into:  the hash is token-based,
    not purely text, so that irrelevant changes in layout, whist spaces, and spelling (e.g.,
    -> vs →) are discounted.  Each individual source file is also hashed.  the compiler emits
    into the generated ELF file a new section .sbom with reference to another new section .sbomstr
    with a data structure that is a table with three columns, the first being an identifier/enum,
    the second and third referencing a string in the
    .sbomstr section. the first column is the type of entry: compiler, source file, output file,
    and more in future.  the second is the associated name (file name, compiler name, output file name, etc)
    and the last is the hash value as ASCII.  The hash algo is SHA256.  The new sections must be
    available at runtime but need to be the last before the sections that are not loaded.  the
    output file hash sum is computed with all the actual section content plus relevant information
    from the ELF data structures like the entry point.
