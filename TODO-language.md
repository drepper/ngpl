To Do List: The Language
========================

Work on all the issues without the checkmark.  Implement them on separate git branches.  Always
add test cases and adjust the language specification.  Once a to do item is complete add the
checkmark, commit the change, and change back to main.

This list holds the language itself: what a program may say and what it means.  The work on the
implementations is kept beside it — the Python interpreter in
[TODO-bootstrap.md](TODO-bootstrap.md), and the compiler, the runtime and the tooling in
[TODO-compiler.md](TODO-compiler.md).

A feature the bootstrap interpreter does not have yet is tagged `[FULL]`, one that is half in
`[~]`.  What that boundary is and how it moves is in [TODO-bootstrap.md](TODO-bootstrap.md).


Foundations
-----------

What the language rests on, recorded here because the completed list below was started after
these were already in place.  Each has a chapter in `spec/spec.md` except where an item says
otherwise.

[x] a definition and an assignment are two different things and are written differently.  A
    definition is headed by `let`, names the thing, may state a type after a colon -- `mut` in
    front of the type where the binding is to be writable -- and gives the value after `=`; an
    assignment writes `←` between the name and the value.  A reader can tell which they are
    looking at from the first token, and a definition cannot be mistaken for a test, `=`
    comparing and `←` storing.

[x] parentheses group an expression and do nothing else; `[` and `]` subscript a container, with
    the comma-separated form for more than one dimension; a call writes its arguments in
    parentheses after the name.  Whether a call needs a delimiter at all is still open, and is in
    Syntax Decisions Still Open below.

[x] a block is either braced or laid out by indentation, both headed by a colon, and the two may
    be mixed.  A body's last statement is its value where the signature hands one back, so
    `return` is written only to leave early.

[x] comments run `//` to the end of the line and `/* … */` across lines, which is why `/` is not
    an operator and division is written `÷`.

[x] a string literal is double-quoted and reads the escapes `\n`, `\t`, `\\`, `\"` and
    `\u{…}`, the last checked where it is written.  A character literal is single-quoted and
    holds exactly one character.  Two pieces are missing: the rule that a simple string ends
    before the end of the line, which is the next item, and the multi-line form, in String and
    I/O below.

[ ] the specification has no chapter on the string literal, so what the scanner does is all
    there is to read.  The brief asks that a simple string cannot hold a newline and must end
    before the end of the line -- an unterminated string is then a mistake on one line rather
    than a run of the file read as text -- and neither the rule nor the escapes are written
    down.  The bootstrap does not enforce it either; that is an item of its own in
    TODO-bootstrap.md.

[x] integer literals are written in decimal, in binary with `0b`, and in hexadecimal with `0x`;
    a float literal is decimal with an `e` exponent or hexadecimal with a `p` exponent, so a
    mantissa and an exponent may use different bases.  The `₂` and `ₕ` suffixes the brief asks
    for are a second spelling and are still open, in String and I/O below.

[x] nothing is written outside a function.  A source file holds definitions -- functions,
    globals, types, macros -- and what runs is what the `@start` function reaches.  The REPL is
    the one place a statement stands on its own.

[x] enumeration types, whose members are reached through the enum's name rather than sitting in
    the global namespace, with the underlying integer type stateable as C++'s `enum class`
    allows, auto-numbering from zero, and `@flag` numbering by powers of two, adding a `nil`
    member where nothing else takes the value zero and admitting the bitwise operations to
    combine, test and remove flags.

[x] binary logic operations on integers, written `∧ ∨ ⊕ ⊼ ⊽ ¬`, element-wise over arrays, with
    `@wrap` where a complement leaves the range.  What is missing beside them is the boolean
    pair, in Operators and Notation below.

[x] the integer remainder, `%`, truncating toward zero as C, C++ and Rust do, with the result
    type resolved as the other arithmetic operators resolve it.  The glyph is the last ASCII
    arithmetic operator and is asked about in Operators and Notation below.

[x] the built-in test system: `@test` marks a test and may name the functions it covers.  A
    standalone test runs before the `@start` function, a test naming functions runs once on the
    first call to any of them as `pthread_once` does, `--test` runs all of them and does not run
    `@start`, and `--skip-tests` suppresses them for a production run.  `assert` and `assert_eq`
    are available everywhere.

[x] exactly one function is the program's entry point, marked `@start`, and `--start NAME` on the
    command line overrides the annotation -- the precedence the brief asks for.  The return type
    settles the exit status: `∅` exits 0, `u8` and `i8` hand their value out.

[x] the `match` statement returns a value. the value is that of the last expression of each arm.
    all arms must return a value of the same type.  Settled the way an array literal settles its
    element type: from what the surrounding text asks for where it asks, and from the first arm
    that states one otherwise, with untyped numbers taking the answer.  An arm that leaves
    rather than arriving states nothing for the others to agree with.

[x] the `if` statement returns a value. the value is that of the last expression of each arm,
    all arms must return a valu of the same type.  If an `if` statement does not have an `else`
    arm the value returned in an `optional` value.  Otherwise it is of the actual type.
    A branch that leaves rather than arriving -- a return, a @noreturn call -- states no type;
    with no else, the branch still has to arrive with something for ∃ to hold.


Execution Modes
---------------

[ ] [FULL] strict mode, where every type is discoverable before the program runs -- Hindley-Milner
    or an equivalent.  A sum type is an answer rather than a failure: where a value's alternative
    is not resolved statically, a dispatcher is instantiated, possibly inlined, that calls the
    version for the type the value turns out to have.  Strict mode is also where an impure
    function is refused outright and where a measured value must carry its unit.

[ ] [FULL] a scripting mode at the other end, where little has to be known in advance: a value
    nothing describes is boxed and carries its type with it, so a program can be written without
    any of the annotations and still run.  What the programmer does write down -- a type, a unit,
    an attribute -- is what buys the efficient execution back, and the two ends are one language
    rather than two dialects.

Insecure mode is a third setting of this kind and is listed under Control Flow and Expressions,
where the block form belongs.


Source Text
-----------

[x] the source is UTF-8.  Every glyph the language uses -- the operators, the arrows, the
    quantifiers -- assumes it, and the scanner reads nothing else.

[ ] a file that is not UTF-8 or a UCS variant is refused with a diagnostic saying so, and running
    the interpreter or the compiler under a locale is a fatal error at startup, before a byte of
    source is read: a locale would make what a program means depend on the environment it was
    read in, which is the one thing a language that fixes its encoding is buying.

[ ] [FULL] a compilation unit may define its own spellings by macro: an ASCII stand-in for a
    glyph that is awkward to type, `[…]` or `⟦…⟧` for a hash literal, `?` and `!` for the
    optional's glyphs.  The definition reaches that unit and no further, so a file says which
    spellings it uses and a reader of another file is not affected.

[ ] [FULL] `⍰` and `⚠` for asking an optional for its value and for taking it or failing, with
    `?` and `!` as the per-unit replacements above rather than as the language's own spelling.
    Today `?`, `??` and `!` are what is written, which is Rust's and Zig's ASCII and not the
    glyph the brief asks for.


Operators and Notation
----------------------

[ ] boolean operations beside the binary ones, spelled with a `₁` after the glyph -- `∧₁ ∨₁ ⊕₁
    ⊼₁ ⊽₁ ¬₁` -- answering 0 or 1 whatever the width of the operands, where the binary ones
    answer bit by bit.  The two have the same range of operations, which is what the subscript
    says: the same question asked of the value rather than of every bit of it.

[ ] a flag enum's operations are written `|`, `&`, `^` and `~`, which are C's spellings in a
    language whose binary logic is written `∧ ∨ ⊕ ¬`.  Two spellings for one operation is what
    `==` was taken out for; the glyphs should reach the flag enums, and whether the ASCII forms
    stay as operators at all is the question this raises.

[ ] the remainder is written `%`, the last of the ASCII arithmetic operators, in a language that
    writes multiplication `×` and division `÷` because a program is read more often than it is
    typed.  Decide the glyph.  It cannot be `mod` written as a word without deciding the wider
    question of named operators, and it should read as a relative of `÷`, which is what the
    integer-division question below is also about.


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

[x] a hash and a set, written ⸨…⸩ with a colon after the first entry saying whether the entries
    have two halves, and typed std.hash(K,V) and std.set(V).  Not { }: that begins a struct
    literal, which is the same shape keys and colons and all, and a braced block -- a parser
    could be taught to guess and a reader could not.  A lookup answers V? rather than raising,
    because a key that is not there is not a value to invent and because ⍳ already answers
    this exact question this exact way.  One type of key and one type of value, settled by the
    same routine an array literal uses, so the diagnostics and the widths-settle-from-one
    behaviour come for free; a key also has to be rememberable, which is to say one of the
    things the language compares exactly.  ⸨⸩ is empty of which of the two it is as well, so a
    type says both and a binding without one is refused, as `let f := []` is.  Entries keep
    the order they arrived in, a hash having no order of its own to expose.  #, ∊, [], ← and
    foreach do for these what they do for an array rather than bringing new spellings; only
    what those cannot say is a member -- keys, values, insert, remove, clear.  foreach learned
    to take a destructuring pattern, which a parameter and a definition already took.

[x] ∪, ∩ and ∖ make one set from two.  They sit where the arithmetic they resemble sits: ∪
    and ∖ where + and - do, ∩ where × does, so `a ∪ b ∩ c` reads as mathematics reads it and a
    reader who knows one precedence knows the other.  Both operands are the container rather
    than a stand-in for what is in it, so they are dispatched before threading, where ⧺ and ∊
    are.  Two sets make one only where they hold the same type, which is what ⧺ asks of two
    arrays; an empty set has no type to disagree with and takes the other's.  The order is
    kept, a union that reordered its result being the same argument the entries lost.

[x] ⊆ and ⊂ ask whether one set is held inside another.  They answer a bool, so they sit with
    the comparisons: what makes a set binds tighter and what combines the answer binds looser,
    which is the shape < sits in.  ⊂ is the proper one, false where the two hold the same
    things, which is the whole of what "proper" means and the only reason to have two glyphs.
    No ⊃ or ⊇: a superset is the same question with the operands the other way round.

[x] ⧺ joins two hashes, the right-hand value winning a shared key, which makes
    `defaults ⧺ overrides` read the way it is written; a key keeps the place it first had.
    Choosing is the one thing joining says that ∪ does not -- ∪ never has to choose, a set
    holding no more about a value than that it is there.  A set is therefore not joined: it
    holds each value once, so joining two would keep nothing the second repeats, which is ∪
    spelled a second way, and a second spelling is what ⊃ and ⊇ were turned down for.

[x] @pre and @post say what has to be true for a function to be asked and what it promises
    about the answer, C++26's shape including naming the result -- @post(r: …).  Written as
    annotations before the function rather than inside the signature: that is where the
    language already puts what is said about a function, so no new grammar and no new place to
    look, and a condition on its own line reads as the sentence it is where several folded
    into a signature crowd the line a reader most needs.  Any number of each, each standing on
    its own, which says what ∧ would say less legibly.  A precondition is read where the
    parameters are bound and blames the caller; a postcondition where the answer is, seeing
    the parameters too so it can relate the two, and blames the function.  A violation is
    reported at the condition -- the sentence the programmer wrote about what should be true --
    rather than at the arithmetic that broke it, with a backtrace to the call.  A condition
    that does not answer a bool is refused.

[x] a postcondition cannot say what a parameter was on entry: Eiffel's `old` and Ada's 'Old.
    Wants a copy taken before the body runs and a name for it.
    Done in both: `@old(e)` reads e once, after the preconditions and before a statement of
    the body has run, and the postcondition sees that.  Any expression, not only a bare
    parameter; each call reads its own, so a recursion is not confused by the one inside it;
    refused anywhere but a @post.  In ngplc it is kept in a slot of its own below the
    temporaries, a temporary being written over by the first thing the body computes; core-2
    remembers a plain value, an array or a struct being a thing it points at rather than a
    value to keep.

[ ] a condition on a type rather than on a function -- an invariant.

[x] a precondition whose arguments are known before anything runs could be settled then.  The
    machinery is static_assert's; joining them up is its own piece of work.
    Done in both: a call written with constants -- literals or arithmetic over them -- has the
    callee's @pre read where the call is written, and a wrong one is reported whether or not
    that call is ever reached.  Nothing is settled where an argument is not known.  In ngplc
    the arguments are read for their values rather than looked at for literals: a parameter's
    type reaches the operands, so `root(2 - 5)` settles rather than folds and there is no
    NK_INT to recognise.  The condition is then read with the parameters standing for those
    values; a name that is not a parameter, a zero divisor, anything unreadable leaves it to
    the run.

[x] @noreturn says control does not come back from a function, and what follows a call to one
    cannot be reached.  A return already says that for what follows it and needs no attribute,
    the statement being right there; a call does not, and the attribute is the only thing that
    can -- said once at the definition, it says it at every call site.  std.exit and std.abort
    are treated as having it: they are not functions the language declares, so they are named
    in the checker, which is a stand-in for an annotation the library cannot yet write.  A
    warning rather than an error, the program being well-formed and possibly mid-edit, and
    only the first of a run is reported.  Stating a return type as well is refused, being a
    contradiction.  What is not checked is whether a @noreturn body really never comes back:
    that is the halting problem in a hat, so the attribute is taken on trust, as C takes it.
    Rust's ! and Zig's noreturn are types the compiler verifies, which is the answer to move
    to when the type system can carry it.

[x] a @noreturn function whose body falls off the end is not reported.  It wants the flow
    analysis that would also tell an if-with-both-arms-dying from a body that simply forgot.
    Done: the analysis was already there for "answers but not on every path", and now answers
    this too.  A way out is a return, std.exit, a call to another @noreturn function,
    `assert(false, …)`, an if whose every branch leaves, a match whose every arm does, and a
    loop whose test never fails and which no break leaves.

[x] ⊃ and ⊇ ask a hash for its keys and for what it holds against them, replacing .keys and
    .values.  Prefix, where # is, and answering arrays: those two are asked often enough to be
    worth a glyph, and asking them the way # is asked keeps a container's questions in one
    shape rather than half operators and half members.  ⊇ asks a set for what is in it and ⊃
    does not, a set having no keys.  The wrinkle: ⊂ and ⊆ are infix and ask whether one set is
    inside another, so a reader who reads ⊃ and ⊇ as their mirror will be wrong.  What buys it
    back is that a superset needs no spelling -- b ⊆ a is the same question -- so the glyphs
    were going spare, and prefix keeps the two uses apart.

[x] = and ≠ compare two hashes or two sets, order aside.  That is the one place the insertion
    order has to be un-kept: it exists so a walk is repeatable, not because a hash has an
    order, and two holding the same things are the same however each was built up.  The answer
    is one truth value for the whole of it -- two arrays compared with = answer element by
    element, an array being threaded over, but these are the operand rather than a stand-in
    for what is in them, so they are dispatched before threading where ⧺, ∪ and ∊ are.  It
    reaches as deep as what is held, which needed a structural equality arrays do not have,
    since = on two arrays never answers one bool.  assert_eq knows them too.

[x] a hash or a set cannot be a key: neither is rememberable, which is the question a struct
    raises as well.  Refused by name: "std.set(i64) cannot be a key: a key is remembered by
    what it is, so it has to be one of the things the language compares exactly".

[x] an array type may be written where a type is compared against: `static_assert_eq(@typeof(e),
    i8[3])`.  A bare name and a tuple type already could, so the spelling @typeof answers with
    was one a program could not write back.  A type name with brackets after it is an array
    type rather than a subscript of anything, which is asked before an empty index is refused
    as one -- an empty dimension being part of the spelling, `u8[2,]`.  A subscript of a value
    with an empty index is still refused.

[x] `let f := []` is refused: an empty array says nothing about what it would hold and a
    binding with no type written down says nothing either, so between them there is no type --
    and a name with no type is a name nothing can be checked against afterwards.  Rows of rows
    of nothing are still nothing, so `[[], []]` is refused the same way.  Being empty is not
    the objection: a dynamic array is allowed to hold nothing, and one whose type is written
    down holds nothing of that type, so `let f : i64[] = []` is an i64[0] that push fills with
    i64.  One row saying what it holds says it for the empty ones beside it.

[x] @typeof answers an array's actual type rather than the word "array".  What an array is is
    what it holds and the shape it holds it in, and both are written down in the type a
    program would give it: i8[3], u8[2,3], u8[2,] where the rows disagree about an extent, as
    a type leaves one open.  "array" said the same thing about every array, so two that hold
    different things or hold them in different shapes compared equal -- @typeof([[1u8,2,3],
    [2,3]]) ≠ @typeof([1i8,2,3]) was false.  An array holding nothing that was never told what
    it would hold still answers "array", having nothing else to report.  Two tests asserted
    that two different arrays had the same type, which was only true because every array did.

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

[ ] a stated width must match exactly, rather than converting, when a value is stored into a
    declared array or binding.  Arguably the truer reading of "one type", but it is a separate
    question from homogeneity and changes scalar assignment as well.

[x] a ragged nested literal is a shape question and is left to the shape checks; whether
    `[[1,2],[3]]` should be refused where no type states a shape is open.  It does not arise:
    a nested literal is a matrix literal and there is nowhere to write one without a type
    stating a shape -- an untyped binding refuses it for saying no type, a plain array type
    refuses it for having two dimensions, and a matrix type refuses ragged rows, the wholly
    open `T[,]` included ("rows of differing lengths are not a dimension; 2 then 1").

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

[x] a lambda cannot be @listable, there being nowhere to write an annotation on one.  A
    partly applied listable function still threads, since the named function is what is
    called in the end.
    Done in both: `@listable λx : i64 → i64: …`, the annotation in front of the λ being the
    only place it could go.  A partly applied listable lambda still threads, for the same
    reason a named one does.  ngplc threads too, over one level: a listable lambda or named
    function handed a T[] where it asked for a T is asked of each element, the containers of
    a call are asked to be of one length, and the answer is an array of what one element
    answers.  Deeper nesting is not core-2.

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

[x] type aliases.  A name for a type, resolved through a chain of them, and interacting with
    coercion the way the type it names does.  This was half of an item that also asked for
    user-defined casts; that half is next.

[ ] [FULL] user-defined cast functions, declared `comptime` and preferred over the built-in cast
    for the same pair of types, with a cast for which neither exists an error rather than a
    guess.  The syntax has to be concise and context-free, which is the constraint Zig's `@as`
    and `@intCast` answer.

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

[x] map type with literal syntax for initialized variables and member-function operations
    (insert, lookup, delete, iterate).

    The hash is in, written `⸨…⸩` and typed `std.hash(K,V)` -- see the completed item above.
    What is left of this entry is the alternative literal syntax a compilation unit may define
    for itself, which is listed under Source Text.

[~] [FULL] set type with opaque representation (bitmask, array/vector, or tree depending on attributes).
    Sets on enumerations restrict to defined values.

    The set is in, written `⸨…⸩` and typed `std.set(V)`, with `∪ ∩ ∖ ⊆ ⊂ ⊇` -- see the completed
    items above.  What is left is the representation: a bitmask where the values are dense
    enough, an array or a tree where they are not, an attribute hinting at the element count to
    choose between them, and a set over an enum admitting only that enum's values.

[ ] [FULL] matrix type: 2D+ built-in data structure with arithmetic operations (multiply, transpose,
    element-wise ops).  Attributes: diagonal, upper/lower triangle, sparse.

    Transpose is specified -- `ᵀ` written after a matrix, `mᵀ[i, j]` is `m[j, i]`, the extents
    exchanged and an open one left open, sharing nothing because a column is not a row the
    operand holds.  See the chapter in `spec/spec.md`.  The bootstrap refuses the glyph by
    name.  What is left here is the arithmetic and the attributes.

[ ] [FULL] an operator that permutes the axes of a higher-rank array, which `ᵀ` deliberately is
    not: `ᵀ` names one exchange and a cube has three to choose from, so it is refused there
    rather than given an arbitrary meaning.  APL's dyadic `⍉` is the shape to look at.

[ ] [FULL] tensor type for limited dimensionality with GPU-offloadable operations.

[ ] [FULL] vector/matrix attributes: sparse, list-backed (O(n) access, stable addresses),
    tree-backed (O(log n) access).

[ ] [FULL] slice/view types for arrays, matrices, and strings following Rust ownership model.

[ ] [FULL] operations that name the whole container rather than a loop over it -- a matrix
    multiplied by a matrix, a vector added to a vector, a reduction over a tensor -- since a loop
    has to be recognised before it can be offloaded and an operator does not.  This is what makes
    the Vulkan target reachable, and it is what `@listable`, `⌿`, `⍀` and `¨` are the beginning
    of.


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

[x] loop break/continue statements.  Non-local exits from nested loops.  Both are in,
    together with a name on the loop so that a statement in an inner one can act on an outer --
    see the item under Static Analysis below.  What a `break` cannot do yet is carry a value
    out, which is listed there too.

[x] multiple statements on one line with semicolon separator -- the bootstrap has carried
    this for some time; the checkmark records it.  The *trailing* semicolon's discard (the
    spec's Rust-mirroring rule) remains full-only: a function whose promised answer the ';'
    would discard is refused by the bootstrap rather than answered differently.

[ ] [FULL] insecure mode scoping: per compilation-unit, function, or block (like Rust unsafe).

[ ] [FULL] lazy evaluation support: lazy attribute on expressions/functions, with eager as default.
    Interaction with coroutines for opportunistic evaluation.

[x] [FULL] Implement tail recursion as a loop.  The language guarantees this.  Add appropriate
    wording to the specification.  The specification's "A Tail Call Spends No Stack" is it.
    A function stating a @post is left as an ordinary recursion, a condition relating the answer
    to the arguments being stated once per call; so is one answering a sized array.

[x] [FULL] the full language guarantees tail recursion to be implemented without stack use. i.e.,
    tail recursion is implemented with a loop. the interpreter does not support this.  add tests
    and update the specification.  tests/compile/t80_tail_recursion.ngpl is the test, and t8N is
    the naming for a file only the compiled program is run for, the interpreter having nothing
    to say about it.


Functions and Combinators
-------------------------

[~] [FULL] purity enforcement: functions pure by default, impure annotation required for global
    variable access.  Strict mode disallows impure functions.
    The annotation is in and travels up the call chain -- see the two items under Static
    Analysis below -- so what is left is strict mode refusing an impure function outright,
    which waits on strict mode.

[ ] [FULL] combinator glyphs for function composition and pipelines (APL/BQN/UIUA-inspired).
    Ranges-library equivalent for container operations.

[ ] [FULL] optional monad methods: and_then, or_else, and other chaining operations on optional values.

[ ] [FULL] user-defined operators with Unicode code points from mathematical operator classes.

[ ] [FULL] prefix/functional form of infix operators (like Forth reverse notation or Haskell sections).


Compile-Time and Metaprogramming
---------------------------------

[~] [FULL] comptime functions: attribute to mark functions as evaluable at compile time when all
    arguments are constant.  if constexpr equivalent for conditional compilation.
    Half of this is in: `comptime fn` marks a function as being there before the program runs,
    which is what lets a macro call it -- and what lets it call itself, since a macro is one
    function and a walk over the program's text has to descend.  It is one function on both
    sides: installed early for the macros, and again in the ordinary way for the program.
    Still open: evaluating an ordinary call at compile time when its arguments are all known,
    and the if-constexpr equivalent.

[x] hygienic macro system: expansion after scanning, before parsing.  Distinct invocation
    syntax from function calls.  Reference Rust and Common Lisp macro systems.
    In, in both of the forms Rust has -- see Macros and Reflection below.  Expansion happens
    after parsing rather than before it, for the reason recorded there: the arguments arrive as
    a parse tree because that is what a macro was asked to take apart.

[~] [FULL] reflection/introspection: access to parse tree in comptime functions.  Create derived
    types and functions.  Match C++26, Rust, and Zig reflection capabilities.
    A macro is reflection that also writes, so what a macro can ask -- kind, name, head,
    arguments, and `※` for what a name refers to -- is what reflection can ask today.  What is
    missing is following a reference to a definition, which waits on the two-pass installation
    item under Macros and Reflection.

[~] [FULL] function replacement: runtime replacement of @replaceable functions via compiled blobs
    with matching type signatures.  Concurrent execution support.  REPL command to override
    replaceability attribute.  (Partially implemented: @replaceable attribute exists.)

[ ] [FULL] string operations at compile time answer a compile-time string: a concatenation, a
    slice, or a formatted value built from constants is itself a constant and may be used where
    one is required -- a name a macro builds, a message a contract carries, a table an
    initializer holds.

[ ] [FULL] a lambda taken apart by reflection and installed under a name in the global namespace,
    which is the other half of the function-replacement item above and what makes an anonymous
    function a first-class object of the language rather than only of the runtime.


Module System
-------------

[x] modules that name and hide: `module a` is a section marker, not a block -- what follows
    belongs to it until the next says otherwise.  A bare name nests in the module in hand, a
    leading period starts from the outside, `module .` returns to the global module; C++'s
    namespace rules with a period for the two colons.  A definition's whole name is its module
    and its own, and a function's object-file symbol carries that and the signature.  Nothing
    leaves a module without @export, and a module that exports nothing is refused.  Unqualified
    names are looked for outward through the enclosing modules.  In both implementations, and
    test_module is a shared test: compiled and run with --test, its output diffed against the
    interpreter's.  tests/test_module.ngpl, spec Chapter 8.

[ ] [FULL] the rest of the module system: importing a module under a shorter name, asking a
    module for something that is not a function (core-2 refuses `mod.name` unless it is
    called), visibility narrower than exported-or-not, and separate compilation -- which is what would make a
    module a unit of anything but naming.  Name mangling with module prefix is done (the
    symbol is module.name(sig) → ret).

    The brief says the opposite of the mangling sentence above: since the language starts from
    scratch there is no reason to mangle, and a name in an object file can be the normalized,
    compact spelling of the module, the name, and the signature.  Decide which, and record it
    with the object-file encoding in TODO-compiler.md.

    The build function landed ahead of the module system, because the compiler's own sources
    needed splitting before either existed: several files are read as if concatenated, and a
    @build recipe names them.  Spec Chapter 8 describes what is there and says plainly that
    it is a stand-in.  The module system subsumes two of its limitations -- that there is one
    text rather than compilation units, and that the order of the file list is significant
    because an enum and a unit must be declared before use.


Contract System
---------------

[~] [FULL] contracts/assertions with human-understandable descriptions.  Inspired by C++26 contracts.
    Pre/post conditions on functions.  Violations can log, terminate, or trigger debugger.
    `@pre` and `@post` are in, and `--contracts` chooses what a violation does -- see the
    completed items above and under Static Analysis below.  What is left is the description a
    condition carries in words, the handler the program provides, and the debugger.

[ ] [FULL] logging facility integrated into the runtime.  Callable from comptime and runtime code.
    Logging functions can terminate the program.


Memory and Lifetime Management
-------------------------------

[~] [FULL] lifetime system akin to Rust: borrow checker, ownership, move semantics.
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


Standard Library
----------------

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

[ ] Add a way for the program to provide its own violation handler for pre- and post-conditions.


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

[x] break and continue, and a name attached to a loop so that one written inside a nested
    loop can act on an outer one.  The name is an identifier and a colon on the line above
    the loop, as in Java and Go; Rust's leading quote is unavailable, since a quote begins a
    character literal.  A name is not a variable: it has no scope, and it can be read only by
    a break or a continue inside the loop it names.  A statement outside every loop, or one
    naming a loop it is not inside, is refused before anything runs, and a lambda body is a
    boundary — a loop around a lambda is not one its body can leave.  A name that nothing
    inside the loop takes draws a warning, since the loop then claims it is left from within
    when it is not.  Neither statement comes back, so the unreachable-statement warning
    covers what follows one.

[ ] a value carried out of a loop by break, as Rust's `break v` does.  It waits on a loop
    being an expression rather than a statement, which is a separate question.

[ ] a violation handler the program itself provides, as C++26 allows, reading a description
    of what broke.  The four semantics are what a handler is called by, and they are in; who
    gets called is a language feature of its own.


Macros and Reflection
---------------------

[x] Add a macro system with hygenic macros.  The macros of the Rust language can server as
    inspiration or more.  The funcitionality must allow to
    - retrieve the parse tree for the parameter(s) of the macro
    - deconstruct the tree in comptime code
    - reconstruct code and insert it into the compilation unit/parsed program
    - follow references to to type, function, or variable definitions
    A set of operations which allow implementing both the C++26 as well as the Rust
    functionality is required.

    Explored on two branches and both merged; see design/macros/README.md and chapter 15
    of the spec.  Shared by both: invocation as f⟦x⟧, so the mark is around
    the arguments (which are what is unusual) rather than on the name; ⟪ ⟫ quoting a piece
    of the program and $ marking a hole in one; expansion over the parse tree, after parsing
    and before every check; hygiene by renaming what a macro binds, with what arrives from
    the caller keeping its own names.

    Expansion cannot happen between scanning and parsing as this list asked, because the
    first line of the same list requires the parse tree of the arguments.  C works that way
    because its grammar is not context-free; this one is, and an invocation is marked, so
    parsing first is available.

    [x] @macro_rules: a macro is a list of pattern → template rules, as syntax-rules and
        macro_rules! are.  Reads as its own specification and needs no evaluator at
        expansion time.  Cannot say "π is among the factors", only "π is written here", so
        2×π×3 needs a rule per shape and no finite list covers a product.
    [x] macro: a macro is a function from syntax to syntax, as defmacro is, with
        kind(), name(), head() and arguments() to take a piece apart, ※ for what a name
        refers to, and ⟪ ⟫ with $ to build one.  Nothing about any operator is built in: a
        macro asks what an expression applies and walks into what it applies it to, which is
        what the example needs and what a list of rules cannot say.  Costs an evaluator at
        expansion time and cannot be read without being run.

    The two are headed by different keywords so that both can be present at once:
    @macro_rules for the rules form and macro for the function form,
    following Rust, where macro_rules! and a procedural macro are the same two halves.
    macro_rules is a keyword only after an @, so the word stays available as a name; macro
    is a reserved word as fn and struct are, which is what heading a definition costs and is
    why the longer name is the one written with an @.

    Both are wanted, as they are in Scheme and in Rust, and both are in.  What each is for:
    the rules form for the majority of macros, which are shorthand -- a shape and what it
    becomes -- and the function form for the minority that have to look at what they were
    handed, which is the case that makes a macro worth having over a function at all.

    ※name is what a name refers to, which C++26 writes as ^^name.  The caret is an ASCII
    constraint this language does not have; ※ is what Unicode calls a reference mark.  ⇑ was
    the other candidate and lost to ↑ already being exponentiation.

[ ] install the program's definitions in two passes -- signatures before expansion, bodies
    after -- so a macro can follow a reference to what a name means.  This is the one item
    of the macro list above that is not implemented, and it is also what attribute macros
    and macros that write definitions rather than expressions wait on.  `comptime fn` covers
    the part of it that is about calling: a function marked that way is installed before
    expansion.  What is left is reading a name the macro was handed and finding what it
    refers to.

[ ] the second half of hygiene: a name a macro's template reads should resolve where the
    macro was written rather than where it was invoked.  With one global namespace the two
    are the same place, so the question waits on modules.

[x] a conditional expression, `a if c else b`, in Python's order.  The value is the first
    where the condition holds and the third where it does not, and only the branch taken is
    read -- which is what lets one stand in front of the thing it guards against.  It binds
    looser than every operator, a chain groups to the right, and else is required, an
    expression that produced no value being no expression.  What tells it from an if
    statement is the line break: an if goes on with an expression only where the token in
    front of it is not one.
    Withdrawn.  An if hands back the value of the branch that runs, which says the same
    thing and also holds a branch of several statements, so `if c: a else: b` is the one
    spelling and this one draws a sentence pointing at it.

[x] check that the two branches of a conditional expression agree in type.  Only what the
    program writes down is read -- a literal, a name's declaration, a struct field, a
    comparison -- so a pair is judged only where both sides say what they are, and a pair
    where either says nothing is left alone.  What agrees: a number with no width stated,
    which settles on what it is asked for; an absent value, which an optional holds along
    with the other side; and two types a declared sum type says belong together, that being
    the whole of what a sum type is for.  Without such a declaration the same pair is
    refused, which is the honest answer -- the two are one value only because something said
    so.

[ ] a fuller pass over what type an expression has.  What is there answers literals, names,
    struct fields and comparisons, which is what the conditional check needed; arithmetic
    answers nothing, width unification between two stated widths being its own question.

[x] a map operator, f ¨ v, spelled as APL spells each.  It asks f of each of the things v
    holds and answers an array of what it said.  Arrays and ranges, as a fold takes; a matrix
    is mapped by rows; an empty container answers an empty array.  It is not made unnecessary
    by @listable: that is a promise the definition makes about every call, and ¨ says the same
    thing at one call, which is where the choice usually belongs.  Unlike APL's, it is a
    binary operator rather than an operator modifier, the fold having made the same
    simplification for the same reason -- derived functions are not values yet.

[ ] ¨ over a hash or a set, which needs an answer to what a map of a hash is -- its values or
    its pairs -- and belongs with the rest of what those containers do.

[x] refuse at the definition a function whose body threads over an array parameter while its
    return type names a scalar -- `fn g3(x : i32[]) -> bool: x > 3`, whose body hands back
    bool[].  A listable operator handed an array answers an array, and the parameter's
    declared type says it is one, so the two settle the shape without running anything.  The
    depth is counted through nested operators, ⧺, ⍴, ¨ and both branches of a conditional
    where they agree; a fold, # and a subscript are left alone, none of them answering an
    array.  What nothing says about -- a call to another function, a name that is not a
    parameter, a generic -- is left to the check that meets the value itself.  Impl methods
    are checked too, which they were not before: _static_return_check was never run on one.

[x] the same check through a struct field: `self.v > 3` where v is declared i32[].  A struct
    says what its fields are and a name standing for an instance says which struct, which
    _struct_vars_of already worked out for the purity checks -- self inside an impl block, a
    struct-typed parameter, and a lambda's own struct-typed parameter all name one.

[x] the same check on a lambda, which states its own parameters and its own return type and
    so is asked the same question.  Every definition is walked rather than every function
    body, so a lambda bound to a global name, bound inside a function, or written into a
    condition is all reached the same way.


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

[x] macro invocation syntax: distinguish from function calls (Rust #[...] style, name
    annotation, or different parameter delimiters).
    Answered: the arguments carry the mark rather than the name, `f⟦x⟧`, since the arguments are
    what is unusual about a macro call.  A definition is headed by `macro` or by `@macro_rules`
    -- see Macros and Reflection below.

[ ] [FULL] whether a name says what kind of thing it names.  Requiring a type to start with an
    uppercase letter or with a fixed glyph would let the syntax drop separators, since the parser
    would know a type where it sees one; requiring uppercase shuts out the scripts that have no
    case, which a customary `T` prefix works around.  Decide from the Unicode character classes
    what may begin a name, an operator, and a type.

[ ] [FULL] whether one glyph may mean one thing before a value and another between two, as APL's
    do and as `⌈`, `⌊` and `⧺` already do here, or whether every glyph has a fixed arity as the
    newer array languages settled on.  Run both and record what each costs a reader and a parser.
