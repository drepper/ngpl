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

[ ] four test files call their tests from main rather than marking them @test -- test_units
    (39), test_float (11), test_power (17), test_roots (16).  run_tests.sh runs a file with
    --test, finds no tests, and reports it green, so 83 test functions do not run.
    test_units.ngpl fails when it is actually run: `let x ¤meter := 5` has no type written
    down, which the bootstrap refuses.

[ ] a builtin cannot be @listable: BuiltinFunc has no field for it and the standard library
    reaches Python methods by another path.  std.sqrt over an array would want it.

[ ] a survey that every full-language feature the bootstrap does not have is refused by name
    rather than misparsed or quietly given another meaning.  The rule is stated above and holds
    for the arbitrary-precision types; nothing checks that it holds for the rest, and a `[FULL]`
    item that lands without one is the way it would be lost.

[ ] the interpreter reads the build function for what it says about search paths and compiler
    flags, as the brief describes, rather than only finding the `@start` function.  Running the
    build recipe belongs to the compiler; reading it does not.

[ ] the source is refused where it is not UTF-8, and running under a locale is a fatal error at
    startup.  The scanner assumes UTF-8 throughout and nothing checks that what it was handed is;
    the language mandate is recorded in TODO-language.md.

[ ] a check that `run_tests.sh` covers every file under `tests/` and that a file with no test in
    it is reported rather than counted green.  The four files above are one instance of a gap
    the harness cannot currently see.

[ ] a newline inside a string literal hangs the scanner: `_read_string` counts the line and
    advances nothing, so the loop never ends and the interpreter has to be killed.  The rule
    the language wants is that a simple string ends before the end of the line, so the newline
    is an error naming the unterminated string; the language side of it is in
    TODO-language.md.
