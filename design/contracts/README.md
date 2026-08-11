# Conditions a Function Holds To

## The Question

A signature says what a function takes and what it hands back.  It has
never been able to say what has to be true for it to be asked at all,
or what it promises about the answer.  Those went in comments, which
nothing checks, or in an `assert` at the top of the body, which is
checked but is not part of what the caller reads.

This is the first piece of what the design brief calls the contract
system, and the piece the rest will be built on.

## The Shape

C++26's, which the brief names as the inspiration: `pre(cond)`, and
`post(r: cond)` naming what comes back.

Where C++26 puts them *in the signature*, these are written as
annotations before the function:

```
@pre(b ≠ 0)
@post(r: r × b = a)
fn divide(a : i64, b : i64) → i64:
    a ÷ b
```

Two reasons.  The language already puts what is said *about* a function
before it — `@impure`, `@listable`, `@noreturn`, `@test` — so a
condition in that position needs no new grammar and no new place for a
reader to look.  And a condition on a line of its own reads as the
sentence it is, which is most of what a contract is for; folded into a
signature between the parameter list and the return type, several of
them crowd the line the reader most needs to see.

More than one of each is allowed, and each stands on its own.  Two
conditions written separately say two things that must both hold, which
is what `∧` would say less legibly.

## What Each Is Read Against

A precondition is read **where the parameters are bound** — after the
arguments have been coerced to the parameter types, before the body.
So it sees the parameters as the body sees them, and it says what the
caller had to get right.

A postcondition is read **where the answer is**, after the return type
has been checked, on both the falling-off-the-end path and the early
`return`.  It may name what comes back, and it still sees the
parameters, which is what lets it relate the two: `@post(r: r = n × 2)`.

## Reported at the Condition

A violation points at the `@pre` or `@post`, not at the arithmetic in
the body that produced the offending value.

That is the whole point of writing it down.  The condition is the
sentence the programmer wrote about what should be true; showing it is
showing the claim that failed, and the reader can see at once whether
the claim or the code is wrong.  The backtrace says which call it was.

A precondition blames the caller and a postcondition blames the
function, since that is what each of them is about, and the two
messages say so in those words.

## Choosing What a Violation Does

Whether a broken condition stops the program is not a property of the
code.  The same source is run while the conditions are being written,
when they are not yet trusted and every violation is worth seeing; and
in production, where one is a reason to stop; and in a hot loop, where
reading them at all may be more than the run can afford.  So the choice
is made per run, on the command line, as `-Werror` is.

C++26's four evaluation semantics are what `--contracts=` takes, and
they are the four because they are the answers to two questions: is the
condition read, and if it is read and does not hold, does the run go on?

| | read | reported | run goes on |
|-|------|----------|-------------|
| `ignore` | no | — | yes |
| `observe` | yes | yes | yes |
| `enforce` | yes | yes | no |
| `quick-enforce` | yes | no | no |

The one that looks redundant is `quick-enforce`, and it is the one with
the clearest reason to exist: reporting a violation means assembling a
message, finding the source line and walking the call stack, and a
build that wants the check without any of that gets the check and a
trap.  Not reporting is not an omission — it is the feature.

### What "Stops" Means Here

C++26 terminates via `std::abort` for both enforcing semantics.  Here
they part:

- `enforce` raises the violation as an **error**, which is how every
  other failure in this language ends a program: a diagnostic at the
  condition, a backtrace, status 1.  It has to be an error rather than
  an abort, because `@expect error` is how a test says a condition is
  meant to be broken, and nothing can account for a signal.
- `quick-enforce` **aborts**, which is the trap C++ means, and which is
  also what makes the two visibly different: the abort says the program
  stopped and nothing says why.

### Reading the Condition Can Fail Too

C++26 has two detection modes: the predicate answered false, or
evaluating it exited via an exception.  The second is a violation as
much as the first — a condition that cannot be read has not been shown
to hold — and it goes through the same four semantics.  This came out
of the change rather than being asked for: once a semantic decides what
a violation does, an unreadable condition has to be one or the other,
and calling it a plain error would have meant `ignore` still stopping
the program.

What is *not* a violation is a condition that answers something other
than a truth value.  That is a mistake in the condition rather than a
report about the program, no semantic makes it true, and none is asked:
it stays an error.

### Why `observe` Ignores `-Werror`

A warning promoted to an error by `-Werror` stops the run.  An observed
violation cannot, since carrying on is the whole of what `observe` was
asked for.  Printing `error:` and continuing would say two things at
once, so the diagnostic stays a warning; a run that wants both is
asking for `enforce`, which is spelled that way.

## What Is Not Here Yet

- **`old`.**  Eiffel's `old x` and Ada's `x'Old` let a postcondition
  compare against what a parameter was on entry.  That needs a copy
  taken before the body runs and a name for it; worth having, and a
  separate piece.
- **A condition on a type, rather than a function** — an invariant.
- **A violation handler the program provides.**  C++26 lets a program
  replace the handler and read a `contract_violation` describing what
  broke.  The four semantics are what the handler is called *by*, and
  they are here; who gets called is a language feature and its own
  piece of work.
- **Checking a condition before anything runs.**  Where the arguments
  are known at compile time, a precondition could be settled then.  The
  machinery for that is `static_assert`'s, and joining them up is its
  own piece of work.

## Status

Implemented: `@pre` and `@post` on named functions and on `impl`
methods, any number of each, with the result optionally named in a
postcondition; conditions read against the parameters and the answer;
a non-`bool` condition refused; violations reported at the condition
with a backtrace to the call; and `--contracts=` choosing between
C++26's four evaluation semantics for the run, over both detection
modes.
