# Leaving a Loop, and Which One

## The Question

There was no way out of a loop except its own condition.

A `while` ran until its test failed and a `foreach` ran to the end of
what it walked, so a search wrote its answer into a flag and then kept
walking, testing the flag on every remaining turn.  The cost is not the
wasted turns — it is that the loop's condition stops saying what the
loop is for.

Two things had to be decided: the statements themselves, which every
language has and spells the same way, and what an inner loop does when
what it found ends the *outer* one.  The second is the reason the first
was worth a design note.

## Nesting Is the Whole Problem

`break` leaves the loop it is written directly inside.  That is the only
reading that works — a reader points at the loop the statement sits in
— and it is the one every language uses.  It is also useless for the
case that matters most:

```
foreach i := 0…9:
    foreach j := 0…9:
        if grid[i, j] = target:
            break            // leaves the inner loop; the outer keeps going
```

The languages that have nothing else make this a flag, or a `goto` past
the loop, or a function whose `return` is the exit.  All three say what
they do somewhere other than where it happens.

So a loop can be named, and `break` can take the name.

## The Notation

Four shapes were considered.  Rust's is out before the comparison
starts: `'outer:` begins with a quote, and a quote here begins a
character literal.  The others were real choices, and the user picked
the second.

| Shape | Written |
|-------|---------|
| Attribute | `@label outer` above the loop |
| **Name and colon on its own line** | `outer:` above the loop |
| Prefix on the keyword | `outer: foreach i := …` |
| A glyph | `⟲outer` above the loop |

What settled it against the attribute is that `@` marks things the
compiler is told *about* a definition — `@impure`, `@listable`,
`@noreturn` — and a loop name is not a fact about the loop, it is a
thing another statement refers to.  What settled it against the glyph
is that this is the one place where the borrowed spelling is universal:
Java, Go and Zig all write a bare name and a colon, and a reader who
has seen any of them needs to be told nothing.

The name goes on the **line above** rather than in front of the loop
keyword so that the loop itself reads exactly as it does when it has no
name.  With the prefix, `outer: foreach i := 0…9:` has two colons doing
two unrelated jobs on one line, and the second is the one that opens the
block.

Nothing was displaced.  An identifier followed by a colon at statement
level was a syntax error before this, and `break` and `continue` were
not used as names anywhere in the tests, the standard library or the
manual.

## Telling a Name From a Statement

The parser decides by what comes *after* the colon: a name and a colon
are a loop name only where the next statement is a `while` or a
`foreach` (or a `comptime` one).  That is a two-token lookahead over
newlines and nothing more, so it stays inside what the grammar can
decide locally — the property the whole language is built to keep.

The alternative was a sigil, which would have made the lookahead
unnecessary.  It was not worth a glyph: the lookahead is bounded, and
the thing being read is short enough that a reader does the same
lookahead without noticing.

## How Far a Name Reaches

A name is not a variable.  It has no scope, holds nothing, and can be
read only by a `break` or a `continue` written inside the loop it
names.  Two unrelated loops may use the same name, since neither is
inside the other and nothing could refer to both.

A loop may name itself and use its own name, which reads as a note
about what the loop is doing.  That is not a special case in the
implementation — the loop is one of the loops the statement is inside —
and refusing it would have meant a rule that exists only to be
explained.

## What Is Refused, and When

A `break` outside every loop, and a `break` naming a loop it is not
inside, are both refused **before anything runs**, at the statement
rather than at the function.  A jump to nowhere is not a thing to
discover on the turn that takes it.

The check walks the loops a statement is inside, which is the same
walk the evaluator does at runtime, so the two cannot disagree about
what is in scope.  A **lambda body is a boundary**: its body is a
separate function, so a loop around the lambda is not one its body can
leave.  Without that, a `break` written in a lambda would raise a
signal that escaped the lambda's call and was caught by whatever loop
happened to be running — a jump between functions, which is the one
thing the language has no way to talk about.

The runtime keeps the same two checks anyway, because there is one
place the static ones do not read: a statement typed at the prompt.

## A Name Nothing Takes

The reverse mistake is quieter: a loop named `outer` that nothing
inside it names back.  The loop reads as though something leaves it
from within, and nothing does.  It is almost always a leftover — the
`break outer` was moved into a function, or replaced by a condition, or
deleted — and what is left behind is a claim about the code that is no
longer true.

A warning rather than an error, on the same grounds as the unused `mut`
it sits next to: the program is well-formed and may be mid-edit.  The
name is where the diagnostic points, which is why the parser records
where it was written rather than only what it said.

A `break` inside a lambda written in the loop does not count as taking
the name.  That falls out of the boundary above rather than being a
second rule: what cannot leave the loop cannot be what the name is for.

## Unreachable, For Free

Neither statement comes back, which is exactly what `@noreturn` says
about a function, so a statement written after one is unreachable for
exactly the reason the existing warning already describes.  Adding the
two node types to `_never_returns` was the whole of it:

```
foreach i := 1…3:
    break
    n ← n + 1       // warning: this statement cannot be reached
```

This is the payoff of having built the unreachable check around a
question — *does control come back from this?* — rather than around a
list of statements.

## What `break` Does Not Do

**It carries no value.**  Rust's `break v` makes a `loop` an
expression, which is a good feature and a different one: it needs a
loop to *be* an expression, and here a loop is a statement.  Nothing
about the notation forecloses it.

**There is no `else` on a loop.**  Python's runs when the loop was not
broken out of, which is a question about the past that reads as a
question about the present, and Python users mostly agree it was a
mistake.

## Comparison with Other Languages

| Language | Naming a loop | Leaving a named one |
|----------|---------------|---------------------|
| C, C++ | none | `goto` past the loop |
| Python | none | a flag, or an exception |
| Rust | `'outer: loop` | `break 'outer` |
| Go | `Outer:` | `break Outer` |
| Java | `outer:` | `break outer;` |
| Zig | `outer: for (…)` | `break :outer` |
| NGPL | `outer:` on the line above | `break outer` |

Zig's `:outer` at the use is the mirror of Go's, and either could have
been read as "the colon marks the name".  The colon is spent on the
definition here, and the use is a bare name — one place per name where
the punctuation appears.

## Status

Implemented: `break` and `continue`, with and without a name, in
`while` and `foreach` loops including `comptime foreach`; names on any
loop at any depth, reaching outward past however many loops lie
between; refusal of a statement outside every loop or naming a loop it
is not inside, statically and at the prompt; the lambda boundary; a
warning for a name nothing inside the loop takes; and the unreachable
warning for what follows either.

Left for later: a value carried out by `break`, which waits on a loop
being an expression.
