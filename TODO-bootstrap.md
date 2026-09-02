To Do List: The Bootstrap Interpreter
====================================

Work on all the issues without the checkmark.  Implement them on separate git branches.  Always
add test cases and adjust the language specification.  Once a to do item is complete add the
checkmark, commit the change, and change back to main.

This list holds the Python interpreter in `interp/`: what it accepts, what it refuses, and how
well it says why.  A feature is designed and specified in [TODO-language.md](TODO-language.md) and
lands here when the interpreter implements it, so an item in this file is about the implementation
rather than about the language; the compiler, the runtime and the tooling are in
[TODO-compiler.md](TODO-compiler.md).

The bootstrap is finished when it can run the self-hosted compiler.  Nothing here argues for
implementing a feature the compiler's own source does not use.


The Bootstrap Language and the Full Language
--------------------------------------------

The Python interpreter in `interp/` is the **bootstrap implementation**.  What it accepts is the
**bootstrap language**, which is a strict subset of the full language that `spec/spec.md`
specifies.  The subset is defined by the implementation: a feature is in the bootstrap language
when `interp/` implements it, and belongs to the full language until then.

A bootstrap exists to be small enough to write by hand and to carry a self-hosting compiler far
enough to take over.  It does not need every feature, and paying for the ones it does not need
would defeat the point of having one.

Two rules hold:

- The subset is strict.  A program the bootstrap accepts means the same thing in the full
  language.  The bootstrap never accepts what the full language rejects, and never gives an
  accepted program a different meaning.
- A feature outside the subset is refused rather than ignored.  Using one is an error naming the
  feature, so a program that runs is one the full language would run the same way.

An outstanding item tagged `[FULL]` is part of the full language and not yet part of the
bootstrap.  When it is implemented the tag goes with the checkmark, and the feature has crossed
into the bootstrap language.  The boundary only moves that way; nothing leaves the bootstrap once
it is in.

An outstanding item with no tag is not a missing feature but a gap in one the bootstrap already
has: something it accepts that it should refuse, or reports less well than it should.  Those are
corrections rather than crossings, so no tag travels with the checkmark.

`spec/spec.md` marks the same boundary from the other side, so a section describing a feature the
bootstrap does not have says so.

### Already Refused

`int` and `float`, the arbitrary-precision types, are full-language only.  A variable, parameter,
return type, struct field, type alias, or lambda parameter naming one is an error in the bootstrap:

    let n : int = 5

    error: 'n': 'int' is an arbitrary-precision type, which the bootstrap
    implementation does not provide; use a sized type such as i64

Nor can a value reach one without being named.  A binding with no type written down would settle
on int or float, so it is refused and the type is asked for:

    let n := 5

    error: 'n': a binding with no type written down settles on 'int', which is an
    arbitrary-precision type the bootstrap implementation does not provide; state
    a sized type, as 'let n : i64 = …'

An array is asked the same question about its elements, and either side may answer:

    let a : i64[] = [1, 2, 3]   // the binding says it
    let a := [1i64, 2, 3]       // one element says it, and the rest take it

A tuple is asked it too, and answered the same two ways, except that one element stating a width
says nothing about the others:

    let t : (i64, str) = (1, "two")   // the binding says it
    let t := (1i64, "two")            // each number says what it is

An *untyped* literal is unaffected while it is being computed with.  It states no width, takes the
one it meets, and is exact until then, so `let big : i64 = 1 « 40` and `static_assert(2 ↑ 200 > 0)`
are both fine.  What the bootstrap does not provide is a *value* that stays arbitrary-precision,
since that needs a representation the sized types do not have.


Completed
---------

[x] `std.implementation` says which implementation runs the program: `name` ("ngpli"),
    `language` ("bootstrap"), `interpreter` (true), `compiled` (false).  The members are
    compile-time constants, so `static_assert` reads them, and a test conditionalizes on
    them where implementations are allowed to differ -- which is what lets one test suite
    serve every implementation.  The compiler publishes the same members about itself
    ("ngplc", "core-1", false, true), folded to constants.  tests/test_implementation.ngpl
    and tests/compile/t06_implementation.ngpl.

[x] `÷` and `%` answer exactly at every width.  The evaluator computed the quotient through
    a Python float, which loses precision past 2^53: `(2^64-1) ÷ 3` was off by 341 and
    `(2^64-1) % 10` answered ⁻1025, an impossible remainder.  Truncation toward zero is now
    integer arithmetic throughout.  Found by the conformance suite disagreeing with the
    compiled code, which divides exactly.

[x] `and` and `or` short-circuit, as the specification's operator table says: the right side
    is not read when the left side already answers.  The glyph pair ∧ and ∨ still reads both.
    Both operands are reduced to a truth value, so the result stays bool either way.
    tests/test_short_circuit.ngpl holds the tests, including the guard idiom
    `i < #v and v[i] > 0` that the pair exists for.

[x] a name frozen in the caller is not frozen in the callee.  The evaluator kept one map of
    frozen names for the whole run, so a function called from inside `foreach i := …` could
    not have a mut local spelled `i`.  The callee now starts from a clean slate and the
    caller's map is restored on return.  tests/test_callee_scope.ngpl.

[x] `open_file` answers an optional: ⊨(file) when the file opened, ∅ when it could not be.
    A missing file is an ordinary answer, not a failure, so the caller decides what absence
    means and says so in its own words -- the raw openat error that used to propagate named
    a system call the program never wrote.  ngplc tests explicitly and reports
    "ngplc: cannot open '<file>': no such file or it cannot be read".  A resource inside a
    present optional is owned and released like a bare one: bound, returned, or left as a
    temporary.  tests/test_file_write.ngpl holds the ∅ tests.

[x] an NGPL program can write a file: `dir.create_file(name, mode?)` (creates or truncates,
    applies the stated mode in spite of the umask, so 0o755 means executable),
    `dir.create_dir(name, mode?)` (an existing directory is fine), `dir.open_dir(name)`,
    `file.write(bytes|str)` (writes in full), `file.chmod(mode)`.  The compiler needs to
    emit an executable and no write path existed.  In the same area, `open_file`'s default
    flags carried `O_NOATIME` (0o1000000) mislabelled as `O_CLOEXEC` (0o2000000), so reading
    a file the user does not own failed with EPERM; fixed.  tests/test_file_write.ngpl.

[x] the Python recursion limit is raised in the interpreter's main: the default capped an
    NGPL program at roughly 120 frames of its own (about 8 Python frames per NGPL call),
    too few for a recursive-descent parser over ordinary nesting.

[x] the unused-mut analysis counts a method call as a possible modification: a method may
    take `&mut self` and write through it, which the analysis cannot see from the call, so
    per its own generous rule anything not known to only read counts.  Before this a `&mut`
    struct parameter mutated only through its methods drew a false warning.

[x] nothing in the bootstrap holds an arbitrary-precision value.  A binding with no type written
    down would settle on int or float, so it is refused and the sized type is asked for; that
    reaches a local, a global, and the value of every operator, since it is the binding that
    settles a value rather than the operator that made it.  A lambda's parameters and return
    type were the one declaration site the type check had not reached.  A float literal now
    gives way to a sized operand as an integer literal already did — f64 + a literal was
    answering `float`, the type the bootstrap does not have.  A loop variable over untyped
    bounds is uncommitted rather than an int, so it settles at the first typed thing it meets
    and still indexes.  An array literal settles the same way: one element stating a width says
    what the array is made of, and a binding of one whose elements state none is refused with
    the bracketed type it needs.  A tuple settles nothing between its elements, so each number
    states its own and the diagnostic says so rather than naming a type that cannot be written;
    the tuples the standard library hands back arrive sized for the same reason.  An argument
    to something that states no parameter type — a standard-library call, or an untyped
    parameter — settles nothing either, so what arrives there has to be a number some sized
    type could hold; u128 and i127 are the widest, and a number that fits one is left alone.

[x] a static diagnostic points at what it objected to.  A check answers with the node it
    found as well as the message, DefinitionError carries the position, and the result is
    rendered with the same excerpt and caret a runtime error gets — in a file and at the
    prompt alike.  Definitions that had no position now carry one, so the errors raised
    while installing them are located too.

[x] a complaint about a struct field points at that field's type.  A field is a
    (name, type) pair with nowhere to hold a position, so the struct carries them
    alongside, as a function already did for its parameters, and a layout error names
    the field it is about.  Before this the caret sat on the struct's first line and
    the excerpt showed the first field, which for a complaint about the third left a
    reader counting.

[x] every signature the specification shows now parses.  Sixty-three were written without
    parentheses — `fn add a : int, b : int → int:` — which the parser stopped accepting
    long enough ago that no example carrying one had ever been run.  A check parses each
    one, so the next such drift is caught rather than accumulated.

[x] REPL: interactive read-eval-print loop when no startup function is defined or on request.
    Define functions/variables, call functions, inspect values.  Entered via --repl, when no
    source file is given, or when the source defines no @start function.  Accepts definitions,
    statements, and bare expressions; layout blocks are terminated by an empty line.  A
    definition draws the same warnings it would in a file, pointed at the entry it was typed
    in, and one that is refused still reports what the checks found before the refusal.

[x] -Werror: an interpreter option making every warning an error, so the program does not run
    and the status says so.  It moves the @expect level with the diagnostic — an annotation
    written @expect warning is read as @expect error — so a file that accounts for its own
    diagnostics needs no rewriting.  A source file cannot ask for it: whether a warning is
    worth stopping for is a property of the run, not of the code.  tests/run_tests.sh runs
    every test file a second time under -Werror, so a new unaccounted warning fails the suite.

[x] an interpreter option choosing what a @pre or a @post that does not hold does, following
    C++26's four evaluation semantics: --contracts=ignore (the condition is not read at all),
    observe (reported as a warning, the run carries on), enforce (reported as an error, the
    run stops — the default), quick-enforce (the run stops at once, reporting nothing, which
    is what makes it quick).  Both of C++26's detection modes go through it: a condition that
    answers false, and one that could not be read at all.  A condition answering something
    other than a truth value stays an error under every semantic, being a mistake in the
    condition rather than a report about the program.  observe stays a warning under -Werror,
    since a diagnostic saying error while the run carries on would say two things at once.


Outstanding
-----------

[x] four test files called their tests from main rather than marking them @test -- test_units
    (39), test_float (11), test_power (17), test_roots (16); --test found nothing and
    reported them green, so 83 test functions never ran.  All four are @test-marked now,
    their mains reduced to the announcement, and their print-on-failure assert_true helpers
    replaced with the real assert, which fails loudly.  Actually running them surfaced 53
    rotted tests: bindings with no type written down (`let x ¤meter := 5`, `let q := 3.0 ÷
    2.0`, hex float literals), a float where the bool-only logic rule now asks for a
    comparison, and measured values handed to unit-less parameters -- all fixed, all 83
    green under -Werror.  --test on a file with nothing marked @test or @expect is now an
    error rather than a green report, so the gap cannot reopen quietly.

[x] a builtin can be @listable: BuiltinFunc carries the flag and threads through the same
    machinery a user function does, and the standard library's numeric functions --
    std.sin, std.cos, std.sinpi -- thread over containers one level at a time, a matrix
    met by the question its rows are.  tests/test_listable.ngpl covers the vector, matrix
    and scalar cases; the spec's @listable section names the functions.

[x] the survey ran, found four violations, and pinned every refusal as an output test
    (tests/output/refuse_*).  Found and fixed: an unknown annotation shed its @ and walked on
    as a name (@lazy became the identifier lazy); the optional glyphs ⍰ and ⚠ lexed as
    identifier characters and vanished into expressions; a fast element type slipped through
    the empty-array-literal path (`let a : mut i32fast[] = []` ran); and a function whose
    last expression carried a trailing ';' answered the value where the full language was
    going to discard it -- one program with two meanings, refused at the time and since
    settled: laid out, the ';' drops the value, and in braces it is the separator.  `import` and the glyphs are refused by name; @repr(packed) already was.

    The @flag rule was made whole where the interpreter had only half of it: a bare number
    was refused in an assignment but silently compared, which the specification forbids on
    both counts.  Both halves now refuse in the same words, and .ord() is the door the
    tests use for the bits.  This is the rare case where the interpreter was the one that
    moved -- its own tests asserted the behaviour the specification does not have.

    @flag enums crossed into core-2 when the ELF constants became
    enumerations: automatic values that double from one, the empty
    combination under nil, | & ^ as the set operations, ~ masked to
    the set's own bits, and .ord() answering the number an enumerator
    stands for -- on every enum, in the underlying type, which for a
    flag set is the bits.  tests/compile/t57_flag_enums.ngpl holds the
    two implementations to one behavior.

    A struct field may now state a unit the way a binding does (name ¤unit : type), so the
    ELF structures can say that st_size counts bytes and st_shndx counts section indices.
    The adoption rule was pinned while the boundary moved: an untyped literal adopts
    everywhere, a typed plain value adopts at bindings and fields but is refused at call
    arguments -- and ngplc was brought up to that refusal, which try_fit alone was too lax
    for.  tests/test_field_units.ngpl.

    `ᵀ` joined them when transpose was specified.  It is the same trap the optional glyphs
    were -- a modifier letter, so `isalnum()` answers yes for it and an identifier scanner
    swallows it silently -- which is why the name scanner now stops there rather than the
    refusal being left to catch a glyph that never reaches it.  tests/output/refuse_transpose.

[x] the interpreter reads the @build function before anything runs.  A recipe is handed the
    build it declares on and what the command line said --
    `fn build(b : &mut std.Build, o : &std.Options)`, the second left off where the recipe
    does not read it and each of its members ∅ where the command line said nothing -- and
    adds to it: an
    executable per output through b.add_executable(std.Build.Executable{...}), the search
    paths and the compiler flags through b.search_path() and b.flag(), with b.output_dir
    written and b.host_target read.  At most one @build function, and that one signature.
    The readers std.build once answered through are gone with it: what a recipe declares is
    the compiler's to act on, not the program's to observe.  tests/test_build.ngpl; spec
    Chapter 8.

[x] the interpreter takes several source files and reads them as if they were one,
    concatenated in the order named; a file boundary is a line boundary, and a diagnostic
    says which file and which line within it, so a file reports the same positions alone
    as beside twenty others.  Everything after a bare -- is the interpreted program's.

[x] the source is refused where it is not UTF-8, with the byte, its line and column, and the
    decoder's reason; a locale that selects an encoding other than UTF-8 (C, POSIX and unset
    pass -- they name no conflicting one) is fatal at startup, since honoring it halfway
    would corrupt quietly.  tests/output/source_not_utf8 and locale_not_utf8.

[x] `run_tests.sh` refuses to run when a `tests/*.ngpl` file is not registered in its list,
    naming the stragglers, and `--test` on a file with no @test and no @expect exits with
    "no tests" instead of a green zero.  Both halves of the gap the four files fell through
    are closed.

[x] an unfinished call that meets a declared type is an arity mistake, named: "'addup' was
    called with 2 of its 3 arguments; a call this unfinished answers a function, not i64" --
    at bindings and at parameters alike, since no type annotation names a function.
    Currying whose result goes on to be called is untouched.  tests/test_curry.ngpl holds
    both refusals.

[x] a newline inside a string literal is an error naming the unterminated string -- "string
    literal is not closed before the end of the line" -- where it used to advance nothing
    and hang the scanner until killed.  tests/output/string_newline.

[x] a global may be an immutable array of constants, built by the same init function the
    image runs before `@start` that builds a global dictionary: `let SQUARES : i64[] =
    [0, 1, 4, 9]`, refused where it is `mut` and where an element is not a constant the
    compiler can see.  A table read on every operation -- the IR's reads/canon/copies
    masks -- is written once beside the program instead of being rebuilt by the function
    that reads it.  tests/compile/t79_global_table and refuse/global_array_{mut,computed}.

[x] `std.fs.cwd().has_file(p)` answers whether a name is a plain file, asked with statx and
    without opening it: a candidate that is not there costs one call and no descriptor, and
    a directory answers false where an open for reading would have said yes to something
    that reads as nothing.  The import resolver and the recipe's source resolver both asked
    by opening and closing; they ask this now.  On x86-64 the emitter gained the `sysc`
    operation, so a runtime routine written once as portable IR now serves all six machines
    rather than being hand-written for the pioneer as well.  tests/compile/t80_has_file and
    refuse/has_file_{pure,two_args}; spec, "Asking Without Opening".

[x] `std.fs.cwd().file_id(p)` answers the pair (device, number on it) a name is, from one
    statx and without opening it, and (0, 0) where the name answers to no file to read --
    no file has the number 0, so the pair carries the absence without an optional.  The
    import reader resolves a name to that pair together with the path, and consults the
    files it already holds before opening: a file reached under a second name is
    recognized before a descriptor is spent on it, where it used to be recognized from the
    descriptor's own statx afterwards.  tests/compile/t81_file_id checks that the two ways
    of asking -- the name and a descriptor opened from it -- answer the same file.

[x] a match over an enumeration dispatches through a table kept on the node -- member value
    to arm, built the first time it runs -- and has a compiled form, so a hundred-arm match
    is one probe rather than a walk down the arms twice over.  Enumerators take the fast
    paths through unwrapping, comparison and .ord(); a unit's dimension is one precomputed
    tuple; converting a value to the measure it already carries is nothing.  Sampled
    self-compile 1806 s → 1604 s on the same source, identical binary.

[x] the compiler checks a multi-key match arm's body once.  It checked it once per key, and
    the second pass met nodes the first had settled -- so a body that compared the subject
    against a member was refused with "an enum is asked about its own kind" where the
    interpreter ran it.  tests/compile/t82_match_keys_body.

[x] the compiler's own flow control, first pass: 71 `if #v > 0:` guards around one loop are
    gone (an empty range runs zero times in both implementations); fills are `n ⍴ x`;
    the scope copies are slices; pop-to-empty loops are `v ← []`; nine literal tables are
    global constants; lower.intern, the parser's name tables and comptime's lookups hash
    through names.Names, which grows now and lets a name answer a value of its own.  `⍴`
    in the interpreter takes any scalar filler and a measured count, as the compiler
    does.  design/array-ops/README.md holds the census and what waits on the language.

[x] the compiler reads `f ¨ v`, `f ⌿ v`, `f ⍀ v`, `f ⌿ (v, init)` and an operator before a
    fold glyph (`+⌿ v`), with a function's name or an operator on the left; a λ there is
    the full language's and is refused by name.  Each lowers to a loop with a direct call
    or the operator's instruction per element, so the six backends see nothing new.
    tests/compile/t85_each_fold and refuse/{each_lambda,fold_arity,each_not_array}.

[x] `⍸ b`, `v[ix]` and `v[ix] ← w` -- where, gather and amend -- in both implementations:
    the filter and the masked store without a loop or a branch.  A subscript by an array of
    indices is told from a subscript by its type; the indices are measured as the array's
    own subscript is, and every one is bounds-checked.  Spec "Where, Gather and Amend";
    tests/compile/t86_where_gather_amend and refuse/{gather_unit,where_not_bool,amend_type}.

[x] `v[lo…step…hi]`, `⍋ v` and `sep ⋈ parts` -- stepped slices, grade and join -- in both
    implementations: the column of a packed table, the order that sorts, the one
    concatenation ⧺ does not say.  ⍋ is a stable merge sort in the portable runtime, run
    on all six machines; the compiler orders numbers, the interpreter strings too.  Spec
    "Stepped Slices" and "Grade and Join"; tests/compile/t87_stepped_slice, t88_grade_join
    and refuse/{join_parts,grade_strings,sslice_string}.
