# Static Analysis: Effects and Unused Values

## The Question

Two things a program can write are almost always mistakes, and both can
be found without running it:

1. A statement that computes a value nothing reads.
2. A function that has a side effect without saying so.

The language already had `@impure` for the second, but it only governed
access to mutable globals, and only when the access actually ran.  A
function could print, or call something that printed, and still read as
pure.  The question is what the two checks should refuse, what they
should leave alone, and whether either is a warning or an error.

## A Value Nothing Reads

### What the check has to decide

For a statement that is a bare expression, three things could be true:

- the value is the point, and dropping it is a mistake;
- the effect is the point, and the value is incidental;
- the statement is the function's result.

Only the first is worth reporting, and separating it from the other two
is the whole of the design.

### Considered

**gcc's route: annotate the declarations that matter.**  `warn_unused_result`
on a function says its callers must read the result.  It is opt-in
because C is full of functions returning a status nobody has ever
checked, and turning the default around would drown a program in
diagnostics.

**The chosen route: every non-`∅` return type means it.**  A signature
is a promise, so `fn f() → i64` says a caller gets an `i64`; a call
that ignores it is not using the function as declared.  A function
meant to be called for its effect returns nothing, which is the shorter
signature and already the one the language recommends.  There is no
history of status-returning functions to preserve.

Rust takes the same view for its own `#[must_use]` types but not for
functions in general; Zig goes furthest, refusing *any* discarded value
including one from a function whose result is a status, and requiring
`_ = f()` to drop it.  What is adopted here is Zig's strictness with
the `∅` return type as the escape that does not need writing down, and
`_ ←`, which the language already has as a discard target, as the way
to say a value is deliberately dropped.

### What is left alone

- **The last statement of a body.**  It is what the function hands
  back.  The interpreter returns it whatever the signature says, so
  calling it unused would be wrong as well as unhelpful.
- **A call to a function returning `∅`.**  Nothing was dropped.
- **A call to an `@impure` function**, and any statement whose
  expression contains one.  The effect is why the line is there.
- **A call the check cannot resolve** — a member function of a built-in
  type, a builtin, a call through a name whose type is not written
  down.  Nothing is claimed about a declaration the check cannot read;
  a diagnostic that says a line is pointless has to be right.
- **`?`, `static_assert`, `static_assert_eq`.**  Each does something
  besides produce a value.

The conservative treatment of unresolved calls is the reason the check
can be an error rather than a warning: everything it reports, it can
show the declaration for.

### Error, not warning

There is no reading of `doubled(21)` as a statement under which the
program is right.  Either a binding is missing or the value is not
wanted, and the second takes one token to say.  A warning would leave
both open, and in a large program would be scrolled past.

## Effects That Say So

### What counts as an effect

Writing to a mutable global was already one.  Writing to the program's
output is the other: `std.print` and `std.println` are how a program
changes something outside itself, and a function that calls one is not
a function of its arguments.

The third case is the one that makes the annotation worth anything: a
function that *calls* an impure function has that function's effect.

### Considered

**Leave propagation out**, which is where the language started: only
the function that touches a global is impure, and callers say nothing.
This keeps the annotation count low, and that was the stated reason.
But it also makes the annotation's absence meaningless — a function
without `@impure` might still print, three calls down — so a reader who
wants to know whether a function is pure has to read the whole call
graph, which is exactly what the annotation was supposed to save.

**Infer impurity instead of requiring it.**  The compiler can work out
which functions reach an effect, so it could annotate them itself and
report nothing.  Rejected: the point of the annotation is that it is
written in the source where a reader sees it, and inference puts the
answer somewhere only the compiler looks.  It would also make the
signature of a function change when something three levels down gains a
`std.println`, without a word appearing in its own text.

**Require it, and check propagation** — chosen.  This is Haskell's
`IO`, which travels up every caller, and D's `pure`, which may only
call `pure`.  The cost is real: `@impure` spreads to every function
that can reach an effect, including the startup function of a program
that prints one line, and the test suite gained about two hundred
annotations when the check was turned on.  What it buys is that the
absence of the annotation is a promise rather than a hint.

### Where it is checked

At the definition, not at the call.  A function that is never called is
checked all the same, which is the same rule the `match` and `try`
checks already follow: a gap is a property of the code, not of a
particular run.

Global access stays a runtime check for now, because whether a name is
a mutable global depends on what the interpreter has settled as it
runs.  The two checks therefore report at different times, which the
specification says rather than hides.

## Resolving a Call

Both checks need the same question answered: which function does this
call reach?  For a plain call it is a lookup by name.  For a method
call it needs the receiver's type, which is known when the receiver is

- `self` inside an impl block,
- a parameter whose type is written down,
- a local initialized from a struct literal or from a call whose return
  type names a struct.

Anything else is unresolved, and both checks fall back to their
conservative answers: the purity check says nothing, and the unused
check treats the call as having an effect.

## Status

Implemented in the interpreter, at definition time:

- a statement whose value nothing reads, including inside loops, if
  branches, match arms, and lambdas, catchable with `@expect` at the
  function or at the statement;
- `std.print` and `std.println` requiring `@impure`;
- calling an `@impure` function or method requiring `@impure`.

Not implemented:

- Effects other than output.  Writing to a file through `std.fs` is not
  yet an effect the check knows about, because the call cannot yet be
  resolved to a declaration that says so.
- An impure lambda passed as a value.  The lambda's own body is checked
  as part of the function that writes it, but a call through a
  parameter holding it is not resolved.
- The same checks in the compiler, which does not exist yet.
