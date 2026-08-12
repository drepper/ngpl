# Macros and Reflection

## The Question

The brief asks for two things that sound separate and are not:

> **hygienic macro system**: expansion after scanning, before parsing.
> Distinct invocation syntax from function calls.
>
> **reflection/introspection**: access to parse tree in comptime
> functions.  Create derived types and functions.

and then lists what a macro has to be able to do:

> - retrieve the parse tree for the parameter(s) of the macro
> - deconstruct the tree in comptime code
> - reconstruct code and insert it into the compilation unit
> - follow references to type, function, or variable definitions

The first line of that list settles the first question, and settles it
against the sentence directly above it.  **A macro cannot be handed the
parse tree of its arguments if it runs before parsing.**  Whatever else
is decided, expansion happens on the tree.

That is worth stating plainly because the C preprocessor is the reason
anyone would write "after scanning, before parsing" in the first place,
and C has a reason: its grammar is not context-free.  `a * b;` is a
declaration or a multiplication depending on whether `a` is a type, and
nothing can be parsed until every macro that might define a type has
run.  This language was built the other way on purpose — the grammar is
context-free, and an invocation is *marked*, so the text around a macro
can be read without knowing what the macro is.  Parsing first is
available here.  Spending it to imitate the one language that has no
choice would be paying for someone else's constraint.

So: **expansion runs over the parse tree, after parsing and before any
check.**  What the checks and the evaluator see is a program with no
macro left in it.

## The Worked Example

Every design below is judged against one problem, which is small enough
to write out and sharp enough to separate them.

`sin(x)` takes radians.  Where the argument is a whole number of turns
— `2 × π` — the answer should be exactly zero and is not: π is not a
number `f64` holds, so `x × π` is rounded before the sine is taken, and
`std.sin(1.0 × std.π)` is `1.2246467991473532e-16`.

`std.sinpi(x)` takes *turns* rather than radians and is exact at every
whole one.  So a macro should look at the expression it was written
with:

- where **π is one of the factors**, take that factor out and hand what
  is left to `std.sinpi`;
- otherwise write the ordinary `std.sin` of the same argument,
  unchanged.

It is a good discriminator because it needs all four of the brief's
verbs: retrieve the tree, take it apart (a *product* has factors),
build a new tree from the pieces, and decide by what a name refers to.

## Axis 1: What a Macro Sees

| Sees | Example | Verdict |
|------|---------|---------|
| Characters | C preprocessor, m4 | No. Cannot find "a factor of a product" in a string without parsing it, and re-parsing is what the design is trying to avoid. |
| Tokens | Rust `macro_rules!` | Nearly. Token trees are balanced, so a matcher can find `$a × $b`, but `2 × π × 3` is a flat run of five tokens and nesting has to be re-derived. |
| **Parse tree** | Lisp, Wolfram, Julia, Scala 3, Nim | **Chosen.** The brief asks for it, the grammar allows it, and "what does this expression apply, and to what" is a question about a tree. |
| Typed tree | C++26 reflection, Zig `comptime` | Later. Knowing a name's *type* means expansion after checking, and a macro that writes a definition must run before the thing it writes is checked. This is what "follow references to definitions" will eventually need. |

## Axis 2: How an Invocation Is Marked

The brief requires the mark; the language leaves several ways to write
it.  All were checked against what the lexer already spends.

| Shape | Written | Why not |
|-------|---------|---------|
| Nothing, as in Lisp | `sin(2 × π)` | A reader cannot tell whether the argument is evaluated, which is the one thing that matters at an invocation. The brief refuses it. |
| Rust's `!` | `sin!(2 × π)` | `!` is the unwrap-or-abort suffix. `x!` is already an expression, and `sin!(…)` is decidable but only by lookahead past the name — a reader does the same work. |
| An attribute | `@macro sin(2 × π)` | `@` marks what the compiler is *told about* a definition. An invocation is not a definition. |
| A sigil on the name | `↯sin(2 × π)` | A free glyph, but it says "this name is special" where what matters is "these arguments are not evaluated". |
| **Different brackets** | **`sin⟦2 × π⟧`** | **Chosen.** |

`⟦ ⟧` (U+27E6/U+27E7) was free: the lexer spent `[ ]` on subscripts and
`( )` on grouping and calls, and nothing on these.  The brief itself
floats "different parameter delimiters", and the choice puts the mark
exactly where the difference is — around the arguments, which are the
things not being evaluated — rather than on the name, which behaves
normally.

It also follows Wolfram, where `f[x]` and `f(x)` differ in this same
way, and it leaves `!` and `@` alone.

A mark is only worth having if writing the other one is *caught*, and
the first thing tried against the finished implementation was
`sin(2.0 × std.π)` — which reported `undefined variable: sin`, pointing
at the argument.  Every word of that was wrong: `sin` was defined, the
argument was not the problem, and nothing said what to write instead.
It now names the macro, says which of the two kinds it is, and says how
one is invoked.

That check has to know whether the name is *also* a function, because a
macro and a function are not in the same namespace and a name may be
both — in which case `( … )` calls the function and there is nothing to
complain about.

`⟪ ⟫` (U+27EA/U+27EB) is the matching pair for *quoting*: a piece of
program written down rather than run.  `$` marks a hole in one.  Both
were free.

## Axis 3: How a Macro Is Written

This is where two answers are both good, so both were built.

### Design A — Rewrite rules

Headed by **`@macro_rules`**.  A macro is a list of patterns and what
each rewrites to, in the tradition of Scheme's `syntax-rules`, Rust's
`macro_rules!`, and Wolfram's `:>`:

```
@macro_rules sin:
    ⟪$a × std.π⟫ → ⟪std.sinpi($a)⟫
    ⟪std.π × $a⟫ → ⟪std.sinpi($a)⟫
    ⟪std.π⟫      → ⟪std.sinpi(1.0)⟫
    ⟪$x⟫         → ⟪std.sin($x)⟫
```

Both halves of a rule are ordinary program text with `$a` where a hole
goes.  The first rule that matches decides.

The two designs are named apart on purpose — `@macro_rules` here and
`macro` in Design B — because both are in the language, and a reader
at a definition needs to be able to tell which kind it is.  The name is Rust's, where
`macro_rules!` and a procedural macro are the same two halves.  It is
written as an annotation, which is a small stretch of what `@` usually
means (something said *about* a definition, rather than the definition
itself), and it buys something back: `macro_rules` is a keyword only
after an `@`, so the word is still available to a program that wants it
as a name.  `macro`, heading Design B, is a reserved word as `fn` and
`struct` are — which is what heading a definition ordinarily costs, and
the reason the longer of the two names is the one written with an `@`.

**What is good.** The macro *is* its specification: there is no code to
read, only the shapes it accepts and what each becomes. It cannot loop
except by rewriting to itself (which is caught), cannot read a file,
cannot print. A reader who knows the language already knows how to read
one, because a pattern is written the way the thing it matches is
written. And it needs no evaluator at expansion time at all — matching
and filling in are two hundred lines of tree walking.

**What is not.** Look at the second and third rules. They exist because
`a × b` is one shape and `b × a` is another, and a rule matches a
shape. That is a warning, and the example makes it a failure: **`2 × π
× 3` matches none of the four rules.** The parser reads it as
`(2 × π) × 3`, and no rule describes a product whose left operand is a
product. Rules can be added — but not finitely many, since a product
nests arbitrarily deep.

The design cannot say *"π is among the factors"*. It can only say
"π is written here".

### Design B — Functions over the program's text

Headed by **`macro`**.  A macro is an ordinary function that runs at
expansion time, in the tradition of Lisp's `defmacro`, Rust's
procedural macros, Julia's `macro`, and Nim:

```
// The factors of an expression, however deeply the parser nested them.
@listable
comptime fn factors(e : syntax) → syntax[]:
    if e.head() ≠ ※×:                       // not a product: one factor
        return [e]
    ⧺⌿ factors(e.arguments())                // a product: each of them, joined

macro sin(e : syntax) → syntax:
    let rest : mut syntax[] = []
    let found : mut bool = false
    foreach f := factors(e):
        if not found and f = ※std.π:        // is it π itself?
            found ← true
        else:
            rest.push(f)

    if not found:
        return ⟪std.sin($e)⟫
    if #rest = 0¤ptrdiff:
        return ⟪std.sinpi(1.0)⟫
    if #rest = 1¤ptrdiff:
        return ⟪std.sinpi($(rest[0]))⟫
    ⟪std.sinpi($(std.syntax.funcall(※×, rest)))⟫
```

`syntax` is a piece of the program.  `⟪ ⟫` builds one; `$e` puts a
value back into one — a piece of program as itself, a number or a
string as what a program would write to mean it.

**What is good.** Everything the brief's list asks for is ordinary
code, and the macro can compute as well as rewrite: `$total` writes
back a number worked out at expansion.  Because the walk is the macro's
own, `2 × π`, `π × 2`, `2 × π × 3`, `2 × 3 × π` and `π` are all handled
by one loop that was written once.

**Nothing about multiplication is in the language.**  That is the point
of the shape.  `head()` answers what an expression is *made by* and
`arguments()` what it applies that to, and an operator is what its
expression applies exactly as a function is what a call applies — so
`a × b` and `f(a, b)` are taken apart by the same two questions.  An
earlier version had a built-in `factors()` that
flattened products, which put one piece of arithmetic into the
interpreter and answered only that one question.  What replaced it
answers every question of that shape and puts the arithmetic where it
belongs, in the macro.

**Every piece has a head.**  The first version answered `syntax?` — the
operator or function applied, and `∅` for anything that applies nothing
— which made every use read `head() = some(※×)`, with the reader
unwrapping at each one.  Wolfram does not: `Head[3]` is `Integer`, and
every expression answers.  So a literal answers the type it states
(`1i64` → `※i64`, `1` → `※int`), a string answers `※str`, an array
`※array`, and the optional is gone along with the `some` at every use.

The one case where the language cannot do better is a **name**: a macro
runs before anything is checked, so the type of what `a` reads is not
knowable yet, and what a name answers is that it is a name. Following a
name to its definition is exactly the piece of reflection that waits on
the two-pass install.

**`※` refers to what a name means.**  `※std.π`, `※×`, `※std.sinpi`.
C++26 spells reflection this way and it is the right spelling here for
the same reason: what is wanted is *the entity*, not the text.  The
first version compared `f.name() = some("std.π")` — a string, which
would be defeated by any renaming and says nothing about what the name
refers to.

Where a quote holds whatever text is written in it, `※` holds one
entity, and that difference is the whole distinction between the two
brackets:

| | holds | written |
|-|-------|---------|
| `⟪ … ⟫` | any piece of program | `⟪std.sinpi($a)⟫` |
| `※` | one entity | `※×`, `※std.π` |

**The check and the construction are the same expression.**  `※×` says
what the expression was and then says what to build:
`std.syntax.funcall(※×, rest)`.  So multiplication is named once, and
`funcall` applies whatever it is handed — an operator, a function, a
method — which is what `std.syntax.product` was replaced by.  A macro
can even hand back the head it was given:

```
std.syntax.funcall(e.head(), e.arguments())
```

rebuilds whatever it took apart without naming the operation at all.

An operator handed more than two arguments is applied from the left, so
one call puts back a product that has lost a factor.  It is not handed
the empty case: what an empty product is belongs to the arithmetic the
macro is doing, not to the builder — which is why the example writes
out what "no factors left" and "one factor left" mean.

**A macro cannot recurse, so something else must.**  The first version
of the example carried its own worklist — an array of pieces still to
look at and an index into it — because a macro is one function and the
walk over a nested product needs to descend.  That is a loop written to
avoid a recursion, and it read like one.

`comptime fn` is what removed it.  A function marked that way is
installed before expansion, alongside the macros, so a macro may call
it and it may call itself.  The example is now three lines that say
what "the factors of an expression" means, and the macro says only what
it does with them.

Those three lines are worth reading twice, because the last one is the
language's own idiom rather than a loop: `@listable` makes
`factors(e.arguments())` answer the factors of *each* of the things the
product applies `×` to, and `⧺⌿` joins those into one array. Written
out it is a loop that carries an array and pushes each answer onto the
end of it, which is four lines saying what one says.

The cost of the shorter spelling is honest and worth stating: marking
`factors` listable changes what it does when a *caller* hands it an
array, which is a promise about the signature made for the sake of the
body. Here the threaded reading is the one anybody would want — the
factors of each of them — so the promise is one worth making.

It is one function on both sides: installed early for the macros, and
again in the ordinary way for the program.  What the marker says is
when the function exists, not what it computes.

**What is not.** The macro is a program, so reading it means running it
in your head. It can loop forever (caught by a depth bound only when it
loops through *expansion*; a `while true` in the body just hangs). It
can be made to depend on things a macro should not depend on. And a
reader cannot see the shapes it accepts without reading all of it.

### The comparison, on the one example

| | rules | functions |
|-|-------|-----------|
| `2.0 × π` | ✓ | ✓ |
| `π × 3.0` | ✓ (second rule) | ✓ |
| `π` | ✓ (third rule) | ✓ |
| `2.0 × π × 3.0` | **✗** | ✓ |
| `2.0 × 3.0 × π` | **✗** | ✓ |
| lines to write it | 5 | 28 |
| lines of interpreter | ~250 | ~400, plus an evaluator at expansion time |
| can be read without running | yes | no |

`tests/test_macros.ngpl` writes the same example both ways, one half
after the other, so the two can be read against each other.

## Both, Which Is Why Both Are In

The honest reading of the table is that the two are not competitors at
the same job.

Design A is right for the majority of macros anyone actually writes,
which are shorthand: `assert_eq⟦a, b⟧`, `swap⟦x, y⟧`, `unwrap⟦e⟧`.
Every one is a shape and a replacement, and writing it as a function
would be ceremony around a rewrite.

Design B is right for the minority that have to *look* at what they
were given — which is exactly the case the brief chose to name, and
exactly the case that makes a macro worth having over a function.

Every mature system ends up with both. Scheme has `syntax-rules` and
`syntax-case`. Rust has `macro_rules!` and procedural macros. They were
built on branches of their own so that each could be judged on its own,
and both are now in the language, which is what that judgement came to.

They are headed by different keywords — `@macro_rules` and `macro` —
so that a reader at a definition can tell which kind it is. The longer
name is the one written as an annotation, which costs nothing: it is a
keyword only after an `@`, so `macro_rules` is still a name a program
may use, where `macro` is reserved as `fn` and `struct` are.

Everything else they share: the invocation, the quoting, when
expansion happens, what an invocation may stand for, and the renaming
that keeps a macro's own names out of the caller's way.

## Hygiene

Both forms follow the same rule, which is the reason it is worth
stating once:

> A name the macro **binds** is renamed to something no source file can
> spell.  A name that arrives **from the caller** keeps its own.

The renaming appends `#` and a number, and `#` is an operator glyph, so
no identifier can contain one and no collision is possible.

The test that proves it is the classic:

```
@macro_rules swap:
    ⟪$a, $b⟫ → ⟪
        let t : i64 = $a
        $a ← $b
        $b ← t
    ⟫

// and, written the other way:
//     macro swap(a : syntax, b : syntax) → syntax: ⟪ … ⟫

let t : mut i64 = 1
let u : mut i64 = 2
swap⟦t, u⟧              // t is 2 and u is 1
```

The caller's variable is called `t` and so is the macro's temporary.
Without renaming, the `let t` shadows the caller's and the swap does
nothing. With it, the macro's is `t#1` and the caller's is untouched.

Writing the statement-macro form is what made this real rather than a
claim. With expression templates only, a template *cannot bind
anything* — an expression in this language has no binder — so hygiene
would have been a mechanism with nothing to do.

**What is not covered yet.** The other half of hygiene is that a name a
template *reads* should resolve where the macro was written rather than
where it was called. With one global namespace those are the same
place, so nothing distinguishes them yet; the question becomes real
with modules, and that is where it should be answered.

## Reflection

The two are the same machinery seen from two ends: a macro is
reflection that also gets to write. What is implemented is what the
example needs, and it is worth being exact about the boundary.

| The brief asks | `@macro_rules` | `macro` |
|----------------|----------------|--------|
| retrieve the parse tree of the arguments | via a pattern | `syntax` values |
| deconstruct the tree | pattern matching | `kind()`, `name()`, `head()`, `arguments()`, `=`, `※` |
| reconstruct and insert code | templates | `⟪ ⟫` and `$`, plus `std.syntax.funcall` |
| follow references to definitions | no | `※` and `=` say whether two references are the same one; neither says what it *refers to* |

The last row is the real gap, and it is one gap rather than four: a
macro runs before the definitions of the compilation unit are
installed, so there is nothing yet to follow a reference *to*. Closing
it means installing the program's own definitions in two passes —
signatures first, bodies after expansion — which is a piece of work of
its own and is where `@typeof` on a macro argument, deriving a function
from a type, and C++26-style injection all become possible.

`@typeof`, `@sizeof` and `@unitof` are already reflection of a narrow
kind, and they answer at check time, which is after expansion. That
ordering is not an accident and should be kept: macros write the
program, and the questions about types are asked of what they wrote.

## What Was Rejected Along the Way

- **Expansion before parsing** (the brief's own first line), for the
  reason at the top: the same brief needs a parse tree.
- **Text substitution**, for the same reason and also because there is
  nothing to be hygienic about in a string.
- **A macro that is a `comptime` function with no special marking**,
  Zig's answer. It is a good answer for a language that refuses macros,
  and it cannot express this example: a `comptime fn sin(x: f64)` is
  handed `6.28…`, not `2 × π`, and by then the multiplication has
  already been rounded. The information the macro needs is destroyed
  before the function is entered. This is the sharpest argument for
  having macros at all, and it is why the example was chosen.
- **Attribute and derive macros** (Rust's `#[derive]`, C++26's
  annotations). Worth having, and they need the two-pass install above,
  since they write *definitions* rather than expressions.
- **Reader macros** (Common Lisp's `set-macro-character`), which let a
  program change how the text is scanned. They defeat the property the
  whole language is built around: that any file can be parsed, in
  parallel, without running anything in it.

## The Glyph for a Reference

`※` (U+203B) is what Unicode calls a **reference mark**, which is what
this is.  C++26 writes `^^`, and the caret was worth keeping only as
long as ASCII was the constraint; it is not one here.

The other candidate was `⇑`, which keeps C++26's upward intuition and
whose doubling echoes the doubled caret.  It lost because `↑` is
already the exponentiation operator, and a reader meeting `⇑` beside it
would reasonably read the two as related. `※` resembles nothing else in
the language and says what it is.

## Status

Both forms are in `main` and the full suite is green: 87 test files,
108 output tests, `-Werror` clean.

Left for later, in the order the work suggests: the two-pass install
that lets a macro see definitions; macros that write definitions rather
than expressions; the module question hygiene's second half waits on;
and expansion in the interpreter's file and REPL paths reusing one
entry point rather than two into the same registry.
