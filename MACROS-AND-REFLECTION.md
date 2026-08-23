# Macros and Reflection in NGPL — Analysis, Proposals, Implementations

*A standalone summary.  Not tracked by git.  Written 2026-08-12.*

Everything below is implemented, tested, and **merged to `main`**.  Two
designs were built, each first on its own branch:

| Form | Headed by | Built on |
|------|-----------|----------|
| a macro is a list of rewrite rules | `@macro_rules` | `macros-rules` |
| a macro is a function over the program's text | `macro` | `macros-proc` |

`macros-design` carried the shared analysis and was merged into both.
Both are now in `main`, which is green: 87 test files, 108 output
tests, 166 spec signatures, 12 REPL tests, `-Werror` clean.

Written documents:

- `design/macros/README.md` — the design record
- `spec/spec.md`, Chapter 15 — the normative description of both
  designs, and the table of designs rejected
- `TODO-language.md` — the entry, with the follow-on work

---

## 1. What the brief asked, and the contradiction in it

From the to do list (now `TODO-language.md`):

> **hygienic macro system**: expansion after scanning, before parsing.
> Distinct invocation syntax from function calls.
>
> Add a macro system with hygienic macros. […] The functionality must
> allow to
> - retrieve the parse tree for the parameter(s) of the macro
> - deconstruct the tree in comptime code
> - reconstruct code and insert it into the compilation unit
> - follow references to type, function, or variable definitions

The first line and the third line cannot both hold.  **A macro cannot
be handed the parse tree of its arguments if it runs before parsing.**

The resolution is to keep the list and drop the first line, and the
reason is worth recording because it is a fact about this language
rather than a preference:

- **C must expand before parsing.**  Its grammar is not context-free.
  `a * b;` is a declaration if `a` is a type and a multiplication
  otherwise, so nothing can be parsed until every macro that might
  define a type has run.
- **NGPL need not.**  The grammar is context-free by design, and an
  invocation is *marked*, so the text around a macro can be read
  without knowing anything about the macro.

Expansion therefore runs **over the parse tree, after parsing and
before any check**.  What the static checks, the type rules and the
evaluator see is a program with no macro left in it.

---

## 2. The worked example

Chosen because it needs all four verbs from the brief's list, and
because it separates the two designs cleanly.

`sin` takes radians.  Where the argument is a whole number of half
turns the answer should be exactly zero, and it is not — π is not a
number `f64` holds, so `x × π` is rounded before the sine is taken:

```
std.sin(1.0 × std.π)     // 1.2246467991473532e-16
std.sinpi(1.0)           // 0.0     — takes turns, exact at every whole one
```

**The macro**: where π is one of the factors of the expression it was
written with, take that factor out and hand what is left to
`std.sinpi`; where there is no π, write the ordinary `std.sin` of the
same argument, unchanged.

Both branches added to `std`: `π`, `sin`, `cos`, `sinpi`.

---

## 3. The three decisions, and what was rejected

### 3.1 What a macro sees — the parse tree

| Sees | Where seen | Verdict |
|------|-----------|---------|
| characters | C preprocessor | No. "The factors of a product" is not a question about a string, and there is nothing to be hygienic about in one. |
| tokens | Rust `macro_rules!` | Nearly. Token trees are balanced, so simple patterns work, but nesting must be re-derived: `2 × π × 3` is a flat run of five tokens. |
| **parse tree** | Lisp, Wolfram, Julia, Nim, Scala 3 | **Chosen.** |
| typed tree | C++26 reflection, Zig `comptime` | Later. Needs expansion after checking, and a macro that writes a definition must run before what it writes is checked. |

Also rejected: **`comptime` functions instead of macros** (Zig's
answer).  It cannot express the example — a `comptime fn sin(x : f64)`
receives `6.283…` with the multiplication already rounded.  The
information the macro needs is destroyed before the function is
entered.  This is the sharpest argument for having macros at all.

Also rejected: **reader macros** (Common Lisp).  A program that changes
how text is scanned cannot be parsed without being run, which defeats
context-free parallel parsing.

### 3.2 How an invocation is marked — different brackets

```
sin⟦2.0 × std.π⟧
```

| Candidate | Why not |
|-----------|---------|
| nothing, as in Lisp | A reader cannot tell whether the arguments are evaluated, which is the only thing that matters here. The brief refuses it. |
| `sin!(…)`, as in Rust | `!` is the unwrap-or-abort suffix; `x!` is already an expression. |
| `@macro sin(…)` | `@` marks what the compiler is told *about a definition*. An invocation is not one. |
| a sigil on the name, `↯sin(…)` | Marks the name, where what is unusual is the arguments. |
| **`sin⟦…⟧`** | **Chosen.** The mark sits around the arguments — the things that are not evaluated. Follows Wolfram's `f[x]` vs `f(x)`. `⟦ ⟧` (U+27E6/7) was free; the brief itself floats "different parameter delimiters". |

**`※name`** is what a name refers to.  C++26 writes `^^name`, and the
caret is an ASCII constraint this language does not have.  `※` (U+203B)
is what Unicode calls a **reference mark**, which is exactly what this
is.  The other candidate was `⇑` — it keeps C++26's upward intuition
and its doubling echoes the doubled caret — and it lost because `↑` is
already the exponentiation operator, so a reader would take the two for
relatives.

`⟪ ⟫` (U+27EA/B) quotes a piece of program, `$` marks a hole in one.
Both were free.  `#` was already the length operator and is reused as
the hygiene separator, since no identifier can contain it.

### 3.3 How a macro is written — both answers were built

This is the axis where two answers are genuinely good, so both were
implemented — and, since the end state is both of them present at once,
they are headed by different keywords so that a reader can tell which
kind a name was defined as:

| | Design A | Design B |
|-|----------|----------|
| head | `@macro_rules sin:` | `macro sin(e : syntax) → syntax:` |
| what the word costs | nothing — `macro_rules` is a keyword only after an `@`, so a program may still use it as a name | `macro` is reserved, as `fn` and `struct` are |

The names are Rust's, whose `macro_rules!` and procedural macros are
these same two halves.  `@macro_rules` reads as an annotation, which
stretches what `@` means elsewhere (something said *about* a
definition, not the definition itself); what it buys is that the longer
of the two words is the one that stays free, which is the right way
round.

---

## 4. Design A — rewrite rules (`macros-rules`)

In the tradition of Scheme's `syntax-rules`, Rust's `macro_rules!`, and
Wolfram's `:>`.

```
@macro_rules sin:
    ⟪$a × std.π⟫ → ⟪std.sinpi($a)⟫
    ⟪std.π × $a⟫ → ⟪std.sinpi($a)⟫
    ⟪std.π⟫      → ⟪std.sinpi(1.0)⟫
    ⟪$x⟫         → ⟪std.sin($x)⟫
```

- Both halves are ordinary program text with `$a` where a hole goes.
- `$a` matches anything and remembers it; a name, literal or operator
  matches only itself; a hole written twice matches only where the two
  are written alike.
- Rules are tried in order; the first match decides.
- A template written *under* the bracket rather than beside it holds
  statements, and the invocation then stands on a line of its own.

**Strengths.** The macro is its own specification — there is no code to
read, only shapes and replacements.  It cannot loop except by rewriting
to itself, which is caught.  It needs no evaluator at expansion time:
matching and filling in are tree walking.

**Limit, and it is the example's own.** A rule matches a *shape*.
`a × b` and `b × a` are two shapes — hence two rules — and

```
2.0 × std.π × 3.0        // read as (2.0 × std.π) × 3.0
```

matches **none** of the four.  A product nests arbitrarily deep, so no
finite list of rules covers it.  The design can say *"π is written
here"* and cannot say *"π is among the factors"*.

---

## 5. Design B — functions over the program's text (`macros-proc`)

In the tradition of Lisp's `defmacro`, Julia's `macro`, Nim, and Rust's
procedural macros.

```
// The factors of an expression, however deeply the parser nested them.
@listable
comptime fn factors(e : syntax) → syntax[]:
    if e.head() ≠ ※×: [e] else: ⧺⌿ factors(e.arguments())

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

`syntax` is the type of a piece of the program.  It answers:

| | |
|---|---|
| `kind()` | `number`, `string`, `character`, `truth`, `nothing`, `name`, `operator`, `call`, `array`, `tuple`, `function`, `block` |
| `name()` | `str?` — `some("std.π")` for `std.π`, `∅` for what is not a name |
| `head()` | `syntax` — what it is **made by**: `※×` for `a × b`, `※std.sinpi` for `std.sinpi(x)`, and for what applies nothing the most particular name the language has for it — `※i64` for `1i64`, and `※str`, `※array`, `※name` |
| `arguments()` | `syntax[]` — what it applies its head **to** |

Two pieces of the program are compared with `=`, and are alike where
the same thing is written in both, wherever each was written.

**Nothing about multiplication is in the language.**  An operator is
what its expression applies, exactly as a function is what a call
applies, so `a × b` and `f(a, b)` are taken apart by the same two
questions.  An earlier version had a built-in `factors()` that
flattened products; that put one piece of arithmetic into the
interpreter and answered only that one question.  What replaced it
answers every question of that shape and leaves the arithmetic in the
macro, where it belongs.

**`※` refers to what a name means** — `※×`, `※std.π`,
`※std.sinpi` — spelled as C++26 spells reflection, and for the same
reason: what is wanted is the entity, not the text.  The first version
compared `f.name() = some("std.π")`, a *string*, which says nothing
about what the name refers to and would be defeated by any renaming.

| | holds | written |
|-|-------|---------|
| `⟪ … ⟫` | any piece of program | `⟪std.sinpi($a)⟫` |
| `※` | one entity | `※×`, `※std.π` |

**The check and the construction are the same expression.**  `※×` says
what the expression was, and then says what to build:
`std.syntax.funcall(※×, rest)`.  `funcall` applies whatever it is
handed — an operator, a function, a method — which is what replaced
`std.syntax.product`.  A macro can even hand back the head it was
given:

```
std.syntax.funcall(e.head() ?? ※+, e.arguments())
```

rebuilds whatever it took apart without naming the operation at all.
An operator handed more than two arguments is applied from the left, so
one call puts back a product that has lost a factor; handed none it is
an error, since what an empty product is belongs to the macro's
arithmetic rather than to the builder.

**A macro is one function, so recursion needs `comptime fn`.**  A macro
cannot call the program's functions: they are installed after
expansion, expansion being what decides what they say.  `comptime fn`
puts a function on the other side of that line — installed before
expansion, alongside the macros — so a macro may call it and it may
call itself, which is what a walk over nested program text needs.  It
is one function on both sides: the program calls it as it calls any
other.

**Strengths.**  `factors` recurses, so `2×π`, `π×2`, `2×π×3`, `2×3×π`,
`π×2×3`, `2×(3×π)` and `π` are all handled by one line written once —
`if c: a else: b` choosing without branching, `@listable` answering the
factors of each of a product's arguments, and `⧺⌿` joining them.
Everything on the brief's list is ordinary code.

**Costs.** The macro is a program, so reading it means running it in
your head.  An evaluator is needed at expansion time.  A reader cannot
see which shapes it accepts without reading all of it.

---

## 6. The comparison, measured

| | rules | functions |
|-|-------|-----------|
| `2.0 × π` | ✓ | ✓ |
| `π × 3.0` | ✓ (2nd rule) | ✓ |
| `π` | ✓ (3rd rule) | ✓ |
| `2.0 × π × 3.0` | **✗** | ✓ |
| `2.0 × 3.0 × π` | **✗** | ✓ |
| `π × 2.0 × 3.0` | **✗** | ✓ |
| the default, where there is no π | `std.sin($x)` | `std.sin($e)` |
| lines to write the macro | 5 | 2 + 12 (a comptime helper, and the macro) |
| interpreter code | ~250 lines | ~400 lines + an evaluator at expansion |
| readable without running it | yes | no |
| can loop forever | no (bounded) | yes (a `while` in the body) |

---

## 7. What both share

**Hygiene.** One rule, implemented identically on both branches:

> A name the macro **binds** is renamed to something no source file can
> spell.  A name arriving **from the caller** keeps its own.

The renaming appends `#` and a number; `#` is an operator glyph, so no
identifier can contain one and no collision is possible.  The test is
the classic:

```
@macro_rules swap:                  // or: macro swap(a : syntax, b : syntax) → syntax:
    ⟪$a, $b⟫ → ⟪
        let t : i64 = $a
        $a ← $b
        $b ← t
    ⟫

let t : mut i64 = 1
let u : mut i64 = 2
swap⟦t, u⟧               // t is 2, u is 1
```

The caller's variable is called `t` and so is the macro's temporary.
Without renaming the swap does nothing.

Writing the *statement*-macro form is what made hygiene real rather
than a claim: with expression templates only, a template cannot bind
anything, because an expression in this language has no binder.

**Expansion order.** An invocation is expanded before what is written
inside it, so a macro is handed its argument as the caller wrote it.
What comes out is expanded in turn, so a macro may write another one.
Stopped after 64 rewrites.

**Positions.** Each piece of an expansion keeps the position it was
written at, so what came from the caller points at the caller's text
and what came from the macro points into the macro.

**Errors**, reported at the invocation, both branches:

```
no macro named nosuch is defined; ⟦ … ⟧ invokes a macro and ( … ) calls a function
pair … is invoked here with 1 [argument]
note writes statements, so it is written on a line of its own rather than where a value is wanted
$ … and there is none here
expanding forever did not settle after 64 rewrites
```

and on `macros-proc` also:

```
wrong answers a piece of the program, and this one answered int
pick could not be run: array index 7 out of range (length 2)
※ is written in front of a name or an operator, which is what it refers to
funcall was handed the operator × and nothing to apply it to
```

---

## 8. Reflection: what is there and what is not

A macro is reflection that also gets to write, so the two are one
mechanism.

| The brief asks | A | B |
|----------------|---|---|
| retrieve the parse tree of the arguments | via a pattern | `syntax` values |
| deconstruct the tree | pattern matching | `kind()`, `name()`, `head()`, `arguments()`, `=`, `※` |
| reconstruct and insert code | templates | `⟪ ⟫`, `$`, `std.syntax.funcall` |
| **follow references to definitions** | **no** | **no** |

The last row is one gap, not four: **a macro runs before the
compilation unit's definitions are installed, so there is nothing yet
to follow a reference to.**  Closing it means installing the program in
two passes — signatures first, bodies after expansion — which is
recorded in `TODO-language.md` as its own item.  It is also what attribute
macros, macros that write definitions, and C++26-style injection all
wait on.

`@typeof`, `@sizeof` and `@unitof` are narrow reflection already and
are answered at check time, i.e. *after* expansion.  That order is
deliberate and should be kept: macros write the program, and questions
about types are asked of what they wrote.

---

## 9. Both, Which Is What Was Done

The table in §6 reads like a contest and is not one.  The two designs
do different jobs:

- **Design A** (`@macro_rules`) fits the majority of macros anyone writes, which are
  shorthand — `swap⟦x, y⟧`, `assert_eq⟦a, b⟧`, `unwrap⟦e⟧`.  Each is a
  shape and a replacement, and writing it as a function is ceremony
  around a rewrite.
- **Design B** (`macro`) fits the minority that must *look* at what they were
  given — which is the case the brief named, and the case that makes a
  macro worth having over a function at all.

Every mature system has both: Scheme has `syntax-rules` and
`syntax-case`; Rust has `macro_rules!` and procedural macros.  Both are
merged, rules first — the smaller, safer step, needing no evaluator at
expansion time — and the function form after.

They are named apart so that a reader at a definition can tell which
kind it is, and `$` names a hole in both: in a rule the hole is filled
by what the pattern matched, in a function's quote by what the name
holds.  One idea, read by the parser as one — the surrounding
definition says which.

## 10. Trying them

```
python -m interp --test tests/test_macros.ngpl     # 33 tests, both forms
./tests/run_tests.sh
python tests/run_output_tests.py

# the example, interactively
python -m interp
>>> std.sin(1.0 × std.π)
>>> std.sinpi(1.0)
```

`tests/test_macros.ngpl` writes the same example both ways, one half
after the other, so the two can be read against each other in one file.
The branches `macros-rules`, `macros-proc` and `macros-design` are kept
for the history of how each was arrived at.
