To Do List
==========

Work on all the issues without the checkmark.  Implement them on separate git branches.  Always
add test cases and adjust the language specification.  Once a to do item is complete add the
checkmark, commit the change, and change back to main.


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

[x] float arithmetic reports a result that leaves the range, as integer arithmetic does.
    3e300f64 × 3e300f64 was an infinity and 1e-300f64 × 1e-300f64 a zero; both are
    different numbers from the one the operation has, and a program handed one goes on
    computing with it.  Underflow is reported for × ÷ ↑ only: a zero from + or - is exact,
    since it says the operands were equal.  A subnormal result is kept, being a number the
    format holds; only reaching zero loses the value.  Nothing in the bootstrap can now
    produce an infinity or a NaN, which is what makes the check cheap — the full language
    will have to say how a program asks for them.

[x] a tuple has a type: `(i64, str)`, written the way its values are, and usable wherever a
    type may be written — a binding, a parameter, a return type, a field, an alias, a lambda
    parameter, an array's element type.  The elements are types in their own right, so they
    nest in both directions: `((i64, i64), str)`, `(i64[], str)`, `(i64, str)[]`.  Stating
    the type settles the elements, and a value is measured against it element by element.
    One type in parentheses is that type, so a tuple starts at two elements.  This was the
    gap that made the bootstrap's rule about unsettled numbers unsatisfiable for tuples.
    @typeof answers with the type rather than with the word `tuple`, and a parenthesized
    list of type names is the type they describe, so the answer compares against the type
    as written: static_assert_eq(@typeof(t), (i64, str)).  A definition may name the
    elements instead of the tuple — `let (a, b) := pair`, nesting as the value nests, with
    `_` where an element is not wanted — at a local and at a global alike.  mut reaches
    every name, a repeated name is refused, and a stated type is the tuple's.  A parameter
    may name the elements too, in the same shape, with or without a stated type; a lambda's
    may as well.

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

[x] an integer literal the type its suffix names cannot hold is reported at the definition
    rather than when the code holding it runs, so `300u8` in a function nobody calls is
    found with the rest.  A ⁻ written directly against a literal is part of it, in the
    check and in the evaluator alike, so ⁻128i8 is the i8 whose value is ⁻128; without
    that the lowest value of every signed type was unwritable, as it is in C.  Only a
    literal the ⁻ is written against: in ⁻2↑2 the ↑ takes the 2 first.  A global whose
    initializer objects now says so as a diagnostic rather than a traceback.

[x] a floating-point value a type cannot hold is refused rather than becoming an infinity
    or a zero.  A literal is caught where it is written — `3e400f64` and `1e-50f32`, and
    `3e400` too, since the bootstrap holds an untyped float in an f64 until the
    arbitrary-precision float arrives — and a value being given to a narrower type is
    caught at the binding, the argument, the struct field, the array element, and the
    return.  A return type now settles a float's width as it already settled an integer's.
    A literal that spells zero is zero, which the digits say and the parsed value cannot;
    a subnormal is a number the format holds and is kept.

[x] ⌈ and ⌊ give the larger and the smaller of two numbers, as they do in APL.  The answer
    is one of the operands, so it needs no range of its own and neither operator can
    overflow.  They bind looser than the arithmetic and bitwise operators and tighter than
    the comparisons and …, so `2 + 3 ⌈ 10 - 4` is the larger of the two sums and
    `3 ⌈ 5 = 5` compares the answer.  Operands must be the same kind of number and, where
    they carry units, measure the same thing; arrays are handled element-wise as they are
    for arithmetic.

[x] ⌈ and ⌊ in front of text are the upper and the lower case of it.  The glyphs point up and
    down, which between two numbers is the larger and the smaller and in front of text is the
    upper and the lower, so a reader who knows one reading can work out the other — not true
    of APL's monadic ceiling and floor.  The two cannot be confused, since case is a property
    of text and the extremes of numbers, and taking the monadic position for text keeps a
    name free for rounding.  A character is asked through its string, since one character's
    upper case can be more than one character.

[x] ⍳ says where something is in a container, counted from zero, which is the .find a string
    wanted as well: the left operand is an array or a string, the right an element, a
    character, or a run of characters.  The answer is optional rather than APL's
    length-of-the-container, so a program that forgets to ask is refused rather than reading
    past the end, and it carries the unit an index of that container carries so it can be
    used to look with.  It binds where ⌈ and ⌊ do.

[x] ∊ asks only whether something is there, which a matrix can answer where a position
    cannot: the right operand is a vector, a matrix, or a string, and is looked through
    whole however many dimensions it has.  One thing is asked about at a time and the
    answer is one bool, not APL's shape-of-the-left-operand: a predicate that sometimes
    hands back an array is one a condition cannot be given, and an array on the left would
    make a string on the left mean something -- either a substring test, which is not
    membership, or its characters one at a time.  A string holds characters, so a run of
    them is not one of them, and ⍳ says where a run starts.  What is looked for has to be
    the kind of thing the container holds — a program asking whether a string is among some
    numbers has made a mistake about one of the two — and past that an element is compared
    the way = compares it.  It binds where ⍳ does.

[x] equality is = rather than ==, and ← is the only assignment.  C spells equality == because
    = was taken by assignment before equality needed a glyph; this language assigns with ←, so
    the inherited spelling was paying for a conflict it does not have.  The one that did exist
    was a second assignment spelling: x = 5 stored, which no document asked for -- the manual's
    assignment table lists only ← and the brief says assignment uses ← -- so it went, and with
    it the reason an inline while body could be confused with a typed binding.  A definition's
    = is no conflict: it is consumed at a fixed point before an expression begins, so
    `let b : bool = x = 5` reads without the parser doing anything clever.  What is bought is
    that C's `if (x = 5)` cannot be written: = compares, ← stores, and a comparison in
    statement position is caught by the unused-value rule.  == is refused by name rather than
    as a parse error, every program written before this using it.

[x] inequality is ≠ rather than !=, which followed the equality rename as a separable change.
    != was not wrong, nothing else wanting the spelling; what decided it is that = and != do
    not read as a pair, and ≠ is = with a stroke through it, which is the relation they stand
    in.  != is refused by name as == is.  ! being a type suffix, a type written hard against a
    definition's = -- let x : i64!= 10 -- is refused as it was before, != having been a single
    token then as well.

[x] a number settles a nested literal however deep it sits: `let d := [[1u8,2,3],[2,3,4]]`
    has one element saying what it is and nothing contradicting, so every number in it is a
    u8.  Settling stopped at the outer level before, saw rows rather than numbers and gave up,
    so a nested literal could only be written with a type stated for it however clearly one of
    its numbers had said what it was -- at either scope.  A row is settled by what is in it
    and by what is in every other row, which is the same sentence one level down.  Only what
    is at the bottom is compared between rows: how long each row is belongs to the shape,
    which a type states, so rows of different lengths still settle.

[x] an array is not made from one value.  `let f : i32[4] = 0` filled the array at a
    function's scope and was refused at a global one, and the refusal was about `i32` not
    being an array type: the global path measured the allocated array against the annotation,
    which for a fixed array is only the element type, the shape being in the brackets.  No
    fixed-size array could be declared at global scope at all, not even from a literal.  A
    scalar where an array goes is a type error whatever the type says, so the fill is refused
    at both scopes now -- making many of one thing is what ⍴ is for, and writing `4 ⍴ 0`
    leaves the making visible at the definition.  The global path skips the coercion for an
    allocation as the local one does, so every form that works in a function works at the top
    level.

[x] # is how many things are in a container and @sizeof is how much memory something takes.
    .sizeof answered both in one word -- a count for an array, a size in bytes for a struct --
    and the unit it carried was the only thing that said which; @sizeof was split down the
    same middle, answering storage for a written type and a count for a value, and refusing a
    dynamically sized array outright, which only makes sense if the question was about the
    length.  A byte[] hid all of it, the two being the same number there.  # was free: the
    language comments with // and /* */, so no glyph was displaced.  It takes an array, a
    matrix, a string, or a tuple, and answers the outer dimension -- the one number every
    container has, and the bound for the subscript that indexes it, as APL's ≢ does.  It is
    not threaded, for the same reason: # asks for a container and a container of containers is
    still one container, so nothing is deeper than what it asked for.  Marking it listable
    would change nothing, which is the argument against marking it.  @sizeof now measures
    memory for anything, a dynamic array included: the length is not in the type but the
    memory is a fact about the value.

[x] every function parameter states a type.  A signature is what a reader is given instead of
    the body, so a parameter that said nothing about what it takes left them the body to read.
    A generic covers what an omitted type used to cover and covers it better: T' in two
    positions says the two agree, where two omissions said nothing at all.  `self` is the
    exception, naming the receiver rather than stating what it takes; a pack states a type as
    any parameter does.  A lambda already required one, so this brings named functions and
    methods into line with them rather than inventing a rule.

    A generic had to be made able to hold what an untyped parameter used to hold, which it
    could not: it resolved through runtime_type_of, whose fallback answered "int" for anything
    it did not recognise, so a function, a file or an arena bound the generic to i64 and was
    then refused for not being one.  A parameter that is nothing but a generic now takes the
    value as it is -- unit and all -- and only a type built around a generic, T'[], is filled
    in, since that one states something of its own.  Everything callable answers to one name,
    fn, so a generic meeting a named function in one place and a lambda in another is not told
    they are two types.

[x] an array holds one type of value and one unit, both fixed where it is declared.  Nothing
    remembered a declaration before: the environment stored values alone and the type and unit
    a definition wrote down were used once and dropped, so every later check re-derived what a
    name holds from whatever it held at that moment and a declaration lasted one statement.
    An i32[] took a str[], an i32 took an i64 and became one, a binding with no unit acquired
    one.  Env keeps what the definition said beside the value now, in step with the frame that
    holds it, and an assignment is measured against that rather than against the last thing
    stored.  A unit reaches the elements rather than wrapping the container -- a unit measures
    a number and a container is not one -- so a measured array can be indexed at all, which it
    could not before.  Two spellings, `let d ¤meter : i64[]` and `let d : i64 ¤meter[]`, which
    parse into the same pair and so cannot drift.  A literal whose elements disagree is
    refused, naming both; a width and a unit still settle from whichever element states one.
    Every way in asks one routine -- subscript, push, insert, whole-array assignment, argument,
    lent array, return -- so a row is measured for its length as well as its kind, and ⧺ joins
    only arrays that hold the same thing rather than stamping the left operand's type on the
    right operand's values.  A width still converts with the range check, as at a definition.

[ ] a unit on a sum or product type used as an array's element type.  The unit attaches to the
    element definition rather than to the variable, unless every member is numeric and none
    carries one.  A unit written in a tuple element or a type alias is refused by name today,
    which is where this starts.

[ ] four test files call their tests from main rather than marking them @test -- test_units
    (39), test_float (11), test_power (17), test_roots (16).  run_tests.sh runs a file with
    --test, finds no tests, and reports it green, so 83 test functions do not run.
    test_units.ngpl fails when it is actually run: `let x ¤meter := 5` has no type written
    down, which the bootstrap refuses.

[ ] a stated width must match exactly, rather than converting, when a value is stored into a
    declared array or binding.  Arguably the truer reading of "one type", but it is a separate
    question from homogeneity and changes scalar assignment as well.

[ ] a ragged nested literal is a shape question and is left to the shape checks; whether
    `[[1,2],[3]]` should be refused where no type states a shape is open.

[x] @listable threads a function over what it is handed: a parameter given something deeper
    than it asked for is given a container of what it asked for, so the function is asked of
    each of the things in it.  Depth rather than "is it an array", so a parameter asking for
    a vector is handed one as it is and threaded only over a matrix.  One level is taken off
    and the same question asked again, which is the whole of the recursion -- the dispatcher
    re-enters itself, so every check the ordinary path makes is made again per element, and a
    matrix and a vector pair rows against elements.  What is taken apart together must be the
    same length; nothing is stretched to fit as NumPy stretches it.  The answer has the
    structure of what was taken apart and holds what the function answered, which need not be
    what it was given.  The return type describes one element's result.  Refused at the
    definition for an untyped parameter (the depth the type asks for is what decides), a
    by-reference parameter, a parameter pack, and no parameters at all.  Every arithmetic,
    comparison, logic, shift and saturating operator is marked with it, unary and binary
    alike, which replaced the seventeen lines of element-wise handling that ran once, zipped
    silently, tagged its answer with the operands' type, and sat below the unit rules.  ⧺, ⍳
    and ∊ are not listable, each taking a container as its operand.

[ ] a builtin cannot be @listable: BuiltinFunc has no field for it and the standard library
    reaches Python methods by another path.  std.sqrt over an array would want it.

[ ] a lambda cannot be @listable, there being nowhere to write an annotation on one.  A
    partly applied listable function still threads, since the named function is what is
    called in the end.

[x] ⍳ refuses what the container cannot hold, as ∊ does, both going through one check.  It
    answered ∅ before, on the grounds that = answers false between two values of unrelated
    types and a search is a series of =.  But = is asked about two values a program has in
    hand, where a search is asked about a value and a container, and the container has a
    type: what could ever match is known before anything is compared, so a search that cannot
    succeed is a question that should not have been asked rather than one whose answer is no.
    A width still meets another width and an untyped number still settles on what the
    container holds.

[x] comparing a found position with ∅ was a type error while comparing an absent one was
    not, so (v ⍳ x) = ∅ answered or refused depending on which way the search went.  A
    position carries a unit and the operator dispatch unwrapped the optional to find the
    unit before anything had asked whether there was a value at all.  Whether there is one
    is now settled first for = and !=, which is also what asks whether a run of characters
    is in a string.

[x] writing → ∅ on a function or a method draws a warning, since it says what
    leaving the return type off says and having both spellings invites a reader to look
    for a difference that is not there.  A lambda is exempt, having to state a return
    type at all, and so is a generic return type even on the call where it settles on ∅:
    the signature wrote a type variable, which is a different claim.

[x] a match reads a subject whose type is written down — a parameter, or a let that
    states one — so a missing arm on an optional or a result is reported at the
    definition.  A match on a parameter was left entirely to runtime before, which is
    the commonest place one is written.  A wrong pattern for the type is caught with
    it, and the hint naming what the subject does admit is only given where there is
    one: a plain value has no failure to be written a different way.

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

[x] a function definition may leave the return type off, which says what → ∅ says.
    ∅ is what a function returns when it returns nothing, so naming it repeats what the
    absence already said, and the functions that return nothing are most of what a program
    writes.  Both spellings remain; the tests and the specification use the shorter one.

[x] saturating arithmetic: ⊞ ⊟ ⊠ hold a result at the nearest edge of the type
    rather than reporting it.  With + reporting and @wrap coming round, that is three
    answers to a result that will not fit, each written where it applies rather than set
    for a region of code.  Integers only, since saturation needs a stated range to hold a
    result inside; grouping and units follow the exact operator each answers to, and @wrap
    does not reach them.

[x] an unsigned type reports a result outside its range rather than coming round to it.
    The design mandate says arithmetic overflow/underflow must be reported and says nothing
    about signedness, and treating unsigned as modular exempted exactly the types used for
    sizes and indices, where going below zero is the mistake worth catching.  @wrap is how
    modular arithmetic is asked for; SHA-256 already used it at every one of its additions.
    Coercion answers the same way, so `let y : u8 = 256` is refused as `y + 1` on a u8 of
    255 is.  The diagnostic names the direction, since an unsigned range is nearly always
    left from below.

[x] std.print writes what its template produced and nothing after it; std.println is the
    same call with a newline.  Splitting them keeps the common case the shorter thing to
    write and keeps the name saying what the call does, rather than a flag a reader has to
    look at to know whether a line ended.

[x] an integer literal takes the width of what it is combined with, as an untyped constant
    does in Go, rather than making the expression arbitrary-precision.  The result then lives
    in that width and wraps or overflows as it would, and a shift of it is bounded by it —
    which is what makes (p + 1) « 8 on a u8 parameter an error the definition settles.  `int`
    is a separate thing and still wins against a fixed width, so an accumulator written
    `let total := 0` is not narrowed by the first typed value added to it.

[x] a static diagnostic points at what it objected to.  A check answers with the node it
    found as well as the message, DefinitionError carries the position, and the result is
    rendered with the same excerpt and caret a runtime error gets — in a file and at the
    prompt alike.  Definitions that had no position now carry one, so the errors raised
    while installing them are located too.

[x] a type without brackets names a scalar, so an array meeting one is refused rather
    than read as a shorthand for what its elements are.  The rule holds at a binding, a
    parameter, and a return type.  Where the body writes the array out, the signature and
    the brackets settle it between them and it is reported at the definition rather than
    when the function runs.  sha256.ngpl declared its eight-word hash state u32 and
    nothing said so; it is u32[8].

[x] division is written ÷ rather than /, as multiplication is written × rather than *.
    A slash is not an operator; it keeps only the comment openings // and /*, and one
    used as division says so rather than being read as the start of a comment.  The
    division sign is what a unit formula uses and what a derived unit displays, so a
    speed is declared ¤meter÷second and prints as m÷s.

[x] approximate comparisons for floating-point values: ≅ ≇ ⪅ ⪆ ⪉ ⪊ against = != <= >= < >,
    to within std.comparison_tolerance, which follows APL's ⎕CT in being a fraction of the
    larger operand rather than an absolute epsilon.  Scoping the tolerance is still open.

[x] check a struct-typed parameter at the call, and a binding declared with a struct type,
    so the wrong struct is reported where it is passed rather than at the first field that
    turns out to be missing.

[x] @min and @max giving the extreme values a numeric type can hold, as C++'s
    numeric_limits max() and lowest() do.  Invalid for anything else.

[x] integer types of any stated bit width (i7, u13, u1, i128), with the range, wrapping,
    shift bound, and storage all following from the width.

[x] sum types (tagged unions, equivalent to std::variant).  match construct to deconstruct.

[x] allow lambda functions to have bodies of multiple statement.  Indicate using the usual syntax of
    colon at the end of { } block.

[x] add @enumerate(CONTAINER) which creates an iterator that can be used as in
    foreach i,v := @enumerate([5,4,3,2,1]):

[x] add static_assert, static_assert_eq etc to force the contained tests to be performed at compile time.
    If the expression is not compile-time constant raise a compilation error/crash the interpreter.
    add tests

[x] add @typeof(EXPR) and @resultof(FCT).  These builtin functions return types which can be tested for
    equality with other types.  Use it in examples using static_assert_eq etc.  Depends on static_assert.

[x] Add operators for left and right fold.  The first parameter is a function, the second the
    container, the third the start value.  Choose glyphs, document, test.  Update the sha256 to use
    left fold to compute the return value.

[x] add support for currying function and test it.  Create functions and in a new function curry them
    and then use the result in calls to generate.  Repeat the same with lambda functions.  Document
    the language changes.

[x] implement arena allocators in std.  Provide std.arena.allocator() to get an arena allocator
    with the usual alloc member etc.  Also provide a deinit member function which can be used to
    deallocate all memory.  use it in main of sha256.ngpl instead of std.heap allocator.  After the
    sha256 call call deinit on the allocator

[x] add reset() to arena allocator — free memory but keep allocator usable.

[x] implement generic functions with apostrophe-suffixed type parameters (T', U').

[x] implement parameter packs with … suffix on the last parameter.

[x] add @sizeof(expr) intrinsic as free-function equivalent of .sizeof.

[x] implement comptime foreach for iterating over parameter packs.

[x] rewrite std.format with allocator parameter, C++ std::format-style {} fields, and array formatting.

[x] std.print takes a format string first, as C++'s std::print does, and reads the same
    replacement fields std.format reads.  The specifier is the full C++ grammar —
    fill, align, sign, #, 0, width, precision, presentation type — with two flags of
    NGPL's own for what an NGPL value carries and a C++ value does not: t writes the
    type suffix, u leaves the unit off.  Neither is on by default, so a number is
    written without its width and a measured value with its unit.

[x] floating-point types: f16, f32, f64, bfloat16, float.  IEEE 754 semantics, arithmetic operators,
    literals with decimal/hex mantissa and exponent.


Type System
-----------

[ ] [FULL] arbitrary-precision floating-point type for extended precision computation.

[ ] [FULL] ratio type (arbitrary-precision numerator/denominator).  Automatic decay to float when mixed
    with floating-point values.  Untyped ratio preserved at compile time.

[ ] [FULL] Complex numbers, the rational and imaginary part can be any numeric type as long as both
    parts are the same type.  Use ℜ to access the real part, ℑ to access the imaginary part, ⅈ to
    indicate the imaginary unit, used for parsing and printing.

[x] unit system: attach units (meters, seconds, bytes, count, …) to numeric types.  Enforce
    dimensional consistency: addition requires same unit, multiplication/division derive units.
    Design derived units and attribute-based annotations (e.g., radius vs diameter).


[x] product types (structs) with unspecified layout by default.  Attributes to force layout.
    @repr(C) gives a struct the platform C layout and makes .sizeof, .alignof, and
    .offsetof(name) available; without it those queries are an error rather than a guess.
    Field types without a C representation are rejected where the field is declared.

[ ] [FULL] further @repr kinds beyond C: packed (no padding at all), and possibly a transparent
    single-field form.  Decide whether alignment can be raised as well as suppressed.

[ ] [FULL] type aliases and user-defined cast functions (comptime, invoked in preference to builtins).

[x] add binary power operator ↑.  for integers on the left only allow integers on the right.  Ensure
    overflow and underflow are detected.

[x] to index multi-dimensional objects (matrices etc) support using multiple comma-separated
    expressions within the square brackets instead of using multiple subsequent square brackets

[x] Add a character type.  It must hold UCS4.  Implement foreach on strings by assigning the
    individual values to a variable of the character type.  The character type has a member
    function .ord() (no parameter) to convert to an u32.  The integer types have a .chr() member
    function (no parameter) which creates a character value.  Negative integers produce an error.
    Applying .chr() to a negative constant integer must be recognized at parse/compile-time.
    `char` is its own kind of value: nothing converts to or from it implicitly, so a number
    becomes one only with .chr() and says its number only with .ord(), which is what keeps
    `c + 1` from being a character in disguise as it is in Go.  Beyond a negative number,
    .chr() also refuses one past 0x10FFFF and a surrogate — the latter is what keeps every
    character encodable as UTF-8, which the language requires of its strings.  Characters
    compare by code point; one is written out as itself and displayed as 'a'.

[x] character literals: 'a', with the string keeping its double quotes, so the two say which
    they are before they are read.  The apostrophe that ends a generic type name is taken by
    the name, so a literal after one still reads.  A literal holds exactly one character, and
    '' and 'ab' each say what to write instead.  The escapes are the string's with \' in
    place of \", and \u{…} is checked as it is read.  A member call may follow a character or
    string literal, so 'a'.ord() and "abc".sizeof read; a number literal still cannot, since
    65. begins a float.

[x] building a string from characters: ⧺ joins two sequences, and a string and a character
    are both text, so joining either with either gives a string — which also gives str ⧺ str,
    missing until now even though ⧺ is the operator the specification calls the concatenation.
    `+` was not extended: the reason ⧺ exists is that + should not be overloaded, and joining
    a character with + would read as arithmetic on one.  For the bulk case, .str() on a
    character and on an array of them; it asks for characters rather than bytes, since
    decoding a byte[] is a fallible operation of its own.  An array has no .str(): ⧺⌿ chars
    already says it, and the fold form takes an initial value, which is what an array that
    may be empty needs.

[x] a string built from a vector of integers by folding ⧺ over it: ⧺⌿ ⟨104, 105, 33⟩ is
    "hi!".  Two pieces meet here.  An operator may stand where a fold's function goes —
    +⌿ nums is the sum, and the lambda repeating the operator is no longer needed — which is
    APL's +/ and is read only directly before ⌿ or ⍀, the one place an operator could not
    otherwise appear.  ⧺ over a vector of characters spells the string they make; a vector of
    code points says the conversion where it happens, since ⧺ refuses a number.  Letting ⧺
    read a number as the character it numbers was tried and taken out again: it would have
    made "total: " ⧺ 5 a control character rather than "total: 5" or an error, and which of
    the two a number means is not something the operator can decide.

[x] string indexing and slicing: s[i] is the character at a position and s[i…j] the string
    between two, both counted in characters as .sizeof already counts them.  An index carries
    ptrdiff, which is what an array index carries, since a string is a sequence and this is a
    position in one.  A string is read at a position and not written at one — a character may
    take a different number of bytes than the one it would replace — so an assignment through
    a subscript says so and names what to do instead; before this it quietly did nothing.
    .chars() hands back what a string is made of, as a char[], and is inverse to .str(), so
    the three ways of taking a string apart — foreach, a position, and the whole array — are
    three shapes of one thing and agree about the count.

[x] .ord() and the other conversions answer at compile time, so static_assert('a'.ord() = 97)
    holds.  A member is constant when it answers about the value rather than doing something
    with it: the conversions between a number, a character, and a string, and the queries
    .sizeof and .alignof.  A method of a struct literal is excluded whatever it is called,
    since what a function the program wrote does is not something the check knows.  A
    conversion that cannot be made is then reported where it is written.  Still open:
    searching, decoding a byte[], and classification.


Data Structures
---------------

[ ] [FULL] map type with literal syntax for initialized variables and member-function operations
    (insert, lookup, delete, iterate).

[ ] [FULL] set type with opaque representation (bitmask, array/vector, or tree depending on attributes).
    Sets on enumerations restrict to defined values.

[ ] [FULL] matrix type: 2D+ built-in data structure with arithmetic operations (multiply, transpose,
    element-wise ops).  Attributes: diagonal, upper/lower triangle, sparse.

[ ] [FULL] tensor type for limited dimensionality with GPU-offloadable operations.

[ ] [FULL] vector/matrix attributes: sparse, list-backed (O(n) access, stable addresses),
    tree-backed (O(log n) access).

[ ] [FULL] slice/view types for arrays, matrices, and strings following Rust ownership model.


Control Flow and Expressions
-----------------------------

[x] match statement for deconstructing sum types and optionals.  Done for optionals and
    results: ∃(name) binds a present value or a success, ∄(name) binds a failure's error,
    ∅ matches absence, _ matches the rest, and a value no arm accepts is an error.
    ∄(e) is also an expression, which is how a function originates an error rather than
    propagating one.  Sum types will use the same statement.  Exhaustiveness is checked
    where the subject's type can be worked out -- a call with a declared return type,
    division, a written-out ∃/∅/∄, or a builtin optional-returning method -- and at run
    time otherwise; it will reach further as type inference grows.

[ ] [FULL] loop break/continue statements.  Non-local exits from nested loops.

[ ] [FULL] multiple statements on one line with semicolon separator.

[ ] [FULL] insecure mode scoping: per compilation-unit, function, or block (like Rust unsafe).

[ ] [FULL] lazy evaluation support: lazy attribute on expressions/functions, with eager as default.
    Interaction with coroutines for opportunistic evaluation.


Functions and Combinators
-------------------------

[ ] [FULL] purity enforcement: functions pure by default, impure annotation required for global
    variable access.  Strict mode disallows impure functions.

[ ] [FULL] combinator glyphs for function composition and pipelines (APL/BQN/UIUA-inspired).
    Ranges-library equivalent for container operations.

[ ] [FULL] optional monad methods: and_then, or_else, and other chaining operations on optional values.

[ ] [FULL] user-defined operators with Unicode code points from mathematical operator classes.

[ ] [FULL] prefix/functional form of infix operators (like Forth reverse notation or Haskell sections).


Compile-Time and Metaprogramming
---------------------------------

[ ] [FULL] comptime functions: attribute to mark functions as evaluable at compile time when all
    arguments are constant.  if constexpr equivalent for conditional compilation.

[ ] [FULL] hygienic macro system: expansion after scanning, before parsing.  Distinct invocation
    syntax from function calls.  Reference Rust and Common Lisp macro systems.

[ ] [FULL] reflection/introspection: access to parse tree in comptime functions.  Create derived
    types and functions.  Match C++26, Rust, and Zig reflection capabilities.

[ ] [FULL] function replacement: runtime replacement of @replaceable functions via compiled blobs
    with matching type signatures.  Concurrent execution support.  REPL command to override
    replaceability attribute.  (Partially implemented: @replaceable attribute exists.)


Module System
-------------

[ ] [FULL] module system for composable programs and code reuse.  Name mangling with module prefix.
    Import/export declarations.  Visibility control.

[ ] [FULL] multi-file compilation: compiler accepts multiple source files, build function determines
    compilation strategy.


Contract System
---------------

[ ] [FULL] contracts/assertions with human-understandable descriptions.  Inspired by C++26 contracts.
    Pre/post conditions on functions.  Violations can log, terminate, or trigger debugger.

[ ] [FULL] logging facility integrated into the runtime.  Callable from comptime and runtime code.
    Logging functions can terminate the program.


Memory and Lifetime Management
-------------------------------

[ ] [FULL] lifetime system akin to Rust: borrow checker, ownership, move semantics.
    Stack allocation preferred for local lifetimes.  Partially started: foreach can borrow an
    array with & (read) or &mut (write through to the elements), and a mutable borrow of an
    immutable binding is rejected.  Still missing: borrows anywhere other than a foreach
    iterable, and any check that two borrows do not overlap.

[ ] [FULL] reference counting for boxed values with implicit deallocation.

[x] defer statement for explicit cleanup at scope exit.  Decided against: cleanup is
    attached to the type rather than written out at each acquisition, so a value holding
    an OS resource is released when its binding's scope ends, on every exit path.
    Ownership passes on return and is not taken by parameters.  Implemented for open
    files and directories; close() releases early and makes the value unavailable.

[ ] [FULL] follow resource ownership into globals, struct fields, and array elements, and release
    a resource when the binding holding it is overwritten (rebinding in a loop currently
    accumulates descriptors until the function returns).  Needs the ownership/borrow system.
    Temporaries that are never bound are already released with their statement.

[ ] [FULL] address spaces: named memory regions with read/write/exec flags and access costs.
    Separate code and data address spaces.  Support for accelerator memory, cross-process
    memory, and per-thread memory regions.


Concurrency
-----------

[ ] [FULL] gang concurrency: execution context pools for SIMD-like parallel execution (OpenMP-style).

[ ] [FULL] job concurrency: explicitly created execution contexts for independent tasks.

[ ] [FULL] coroutines: implicit support via lazy evaluation, explicit creation with type system
    representation.  Execution context pool reuse for coroutine scheduling.

[ ] [FULL] communication channels: Transputer/Occam-style channels, Go-style channels.
    Mapping to OS message queues.

[ ] [FULL] memory model: define shared vs private memory for threads.  Not required to follow POSIX.
    Consistent work-splitting for non-associative parallel operations.


Floating-Point
--------------

[ ] [FULL] Inf/NaN handling: fault on Inf/NaN, deferred checking (check after full computation).
    Per-function or per-scope configuration.

[ ] [FULL] precision improvements: Kahan summation, Veltkamp splits / Dekker multiplication,
    FMA operations.

[ ] [FULL] rounding mode control: per-scope or per-function attribute, not compile-time.
    Assumption mode vs active selection.

[ ] [FULL] associativity exploitation: opt-in reordering for non-bit-accurate computation.

[x] add the root functions using unary √, ∛, ∜.  only allowed for floating-point values.  Allowed
    in specification for units.

[ ] Add floating-point constants ⅇ and π for the Euler number and Pi.  Accept them with f16, f32, f64,
    bfloat16 suffix.  Handle them like untyped floats unless a suffix is used.  In the bootstrap
    implementation the value has to be coerced to a finite type.


String and I/O
--------------

[ ] [FULL] multi-line string literals ("""…""" syntax, possibly with " continuation prefix).

[ ] [FULL] binary and hexadecimal number literal suffixes (₂ for binary, ₕ for hexadecimal).
    Also add octal literals: file modes and the S_IF* constants are conventionally
    written in octal, and std.filetype's values have to be spelled in hex without them.

[ ] [FULL] format string type-specific formatting via attributes on type definitions (like Rust
    Display/Debug, Haskell Show).

[ ] a std.print call whose first argument is a literal of the wrong kind — std.print(42) — is
    settled by reading it, so it should be reported at parse time rather than when the branch
    holding it runs.  The same holds for a template whose field count does not match the number
    of arguments after it, where both are written down.  The static diagnostic now carries a
    source position, so the check can move without losing the caret.


Build System and Tooling
-------------------------

[ ] [FULL] built-in build system: @build-annotated comptime function provides build recipe.
    Recompiled when source changes.  SBOM generation in output binary.

[ ] [FULL] JIT compilation in interpreter: background compilation of hot functions, transparent
    switchover.  REPL commands to inspect generated code, machine code, and parse trees.

[ ] [FULL] language server protocol (LSP) mode: expose type information, optimization decisions,
    diagnostics, and code navigation.

[x] REPL: interactive read-eval-print loop when no startup function is defined or on request.
    Define functions/variables, call functions, inspect values.  Entered via --repl, when no
    source file is given, or when the source defines no @start function.  Accepts definitions,
    statements, and bare expressions; layout blocks are terminated by an empty line.  A
    definition draws the same warnings it would in a file, pointed at the entry it was typed
    in, and one that is refused still reports what the checks found before the refusal.

[ ] [FULL] compiler mode: ahead-of-time compilation to native code.  Startup function designation
    via command line or attribute.


Runtime
-------

[ ] [FULL] native runtime using kernel interfaces directly (no libc dependency).  io_uring-based
    async I/O on Linux.

[ ] [FULL] concurrency via clone3 and futex on Linux.

[ ] [FULL] Vulkan code generation for GPU offloading of vector/matrix/tensor operations.

[ ] [FULL] minimal runtime initialization: only pull in code for features actually used.

[ ] [FULL] object file format: possibly custom format supporting partial recompilation.
    Dynamic linking support for system libraries (e.g., Vulkan shared objects).

[x] do not use camelcase for identifiers.  Change all functions in the std module to use
    underscores.  openFile was the last one; it is now open_file, with no alias kept.

[ ] [FULL] add name member function (no parameters) for directory object which returns the absolute path of
    the directory.

[x] exit function to terminate the process with the exit code given as argument.  std.exit(code)
    takes 0…255 and rejects anything outside it rather than truncating; it wins over the @start
    function's return value and produces no diagnostic or backtrace.

[x] abort function to terminate the process with the signal given as argument (if no signal is
    given or it is zero or invalid, use SIGABRT).  std.abort(signal) resets the handler to the
    default first so the parent sees the termination signal, and prints a backtrace before dying.

[x] add backtrace support.  when the program exits abnormally show the call stack of functions of
    the program (not the interpreter).  Add also API in the std module to access the callstack
    at any time.  Frames carry the position execution had reached, the stack travels with the
    failure so it cannot be reported against the wrong error, and std.callstack() returns
    (name, line, column) tuples innermost first.

[ ] [FULL] Add more math functions.  std.sin, std.cos, std.tan, std.cot, std.sec, std.csc, the reverse
    with names like std.asin etc, the variants which implicit multiply the parameter with Pi such
    as std.sinpi and their reverse std.asinpi etc.

[ ] Add the natural logarithm function with the glyph ⍟.


Syntax Decisions Still Open
----------------------------

[ ] [FULL] operator precedence model: traditional precedence, APL-style right-to-left,
    or hybrid (precedence for arithmetic, flat for others).

[ ] [FULL] function call delimiter: parentheses, brackets (Wolfram-style), or no delimiters (Haskell).

[ ] [FULL] integer division semantics: a second operator alongside ÷ (as Python has //),
    an explicit cast requirement, or a modifier on ÷ saying which rounding is meant.

[ ] [FULL] binary/boolean operation semantics on mixed-width integers: reject, zero-extend,
    or repeat.

[ ] [FULL] attribute syntax for variables, functions, statements, blocks, and scopes.

[ ] [FULL] macro invocation syntax: distinguish from function calls (Rust #[...] style, name
    annotation, or different parameter delimiters).

System Environment
------------------

[x] provide access to the command line parameters of the program through a std.args submodule
    with program(), count(), get(i), and all().  The program name is kept out of the parameter
    list.  The interpreter passes everything after a -- separator to the program.

[x] provide read access to the environment of the process through std.env with get() returning
    an optional (so an empty value stays distinct from an unset one), has(), count(), names().

[x] provide access to CPU affinity mask and derived from this number of CPUs to use.
    Also provide access to total number of CPUs, total memory.  Implemented as std.sys with
    affinity(), affinity_cpus(), usable_cpus(), online_cpus(), total_cpus(), page_size(),
    and total_memory().


Static Analysis
---------------

These features need to be implemented at parse-time in the interpreter and at compile-time
in the compiler.

[x] if an expression is not assigned and is not used as a parameter value and does not have
    a declared side effect (@impure attribute for now), mark the statement as unused.  Assume
    all functions not returning ∅ have the equivalent of gcc's warn_unused_result attribute.
    Allow catching the error with @expect.  Reported at the definition as an error, and
    catchable with @expect on the function or on the statement.  Left alone: a call
    returning ∅, a call to an @impure function, a statement holding one, a bare ∅, and a
    call the check cannot resolve to a declaration.  `_ ←` says the value is meant to be
    dropped.  The last statement of a body is the return value where the signature hands
    something back; where it hands nothing back it is not, and that draws a warning rather
    than an error, since the program still runs and the missing piece is usually the
    return type.

[x] Require functions using std.print or std.println to be marked with @impure.

[x] Require functions calling functions marked with @impure to be marked with @impure themselves.
    Both are checked at the definition, so a function that is never called is checked too.
    A lambda's body counts as part of the function that writes it, and a method carries the
    annotation and passes it to its callers the same way a function does.

[x] -Werror: an interpreter option making every warning an error, so the program does not run
    and the status says so.  It moves the @expect level with the diagnostic — an annotation
    written @expect warning is read as @expect error — so a file that accounts for its own
    diagnostics needs no rewriting.  A source file cannot ask for it: whether a warning is
    worth stopping for is a property of the run, not of the code.  tests/run_tests.sh runs
    every test file a second time under -Werror, so a new unaccounted warning fails the suite.
