# A Hash and a Set

## The Question

The language had one container: the array.  Anything asked by name had
to be an array of pairs walked from the front, and anything asked
*whether* had to be `∊` over an array, which reads all of it.

What had to be decided: how a value of either is written, since the
obvious delimiters are taken; how the type is written; what a lookup
answers when there is nothing there; and how much of what an array
already does they should share.

## Why Not `{ }`

Python's `{"a": 1}` and `{1, 2}` are what most readers will have in
their fingers, and the shape is worth keeping.  The delimiters are not
available:

- `{` begins a **struct literal** — `Point { x: 1, y: 2 }` — which is
  the same shape as a hash literal, keys and colons and all.
- `{` also begins a **braced block**, the alternative to layout for a
  function body.

A parser can be taught to guess between them by looking ahead, and a
reader cannot.  `Point { x: 1 }` and `⸨"x": 1⸩` would have been the same
thing written twice, meaning two different things.

So `⸨` (U+2E28) and `⸩` (U+2E29): free, paired, visibly bracket-like,
and not confusable with the parentheses that group an expression.  Only
the delimiters differ from Python — the entries inside read as they do
there, and a colon after the first is what says whether the entries have
two halves.

## What a Lookup Answers

`d[k]` answers `V?` — present or absent — rather than raising for a key
that is not there.

Go answers the zero value and a second result, which invents a value
nobody put there; that is the thing this language most consistently
refuses to do.  Python raises and offers `.get` for the other case,
which is defensible and was the alternative.  What settled it is that
the language already answers this exact question this exact way:
`v ⍳ x` answers an optional position rather than a sentinel, for the
same reason.  A reader who has met one has met the other.

It costs a `??` or a `match` at every read, including where the key is
known to be there.  That is the price of the answer being honest, and
it is the price `⍳` already charges.

## One Type of Key, One Type of Value

The same rule as an array's, arrived at the same way: what a container
holds is what its type says, and a type that said "some of these and
some of those" would say nothing.  The entries are settled by the same
routine an array literal uses, so a hash gets the same diagnostics and
the same widths-settle-from-one-element behaviour for free.

A key has the extra requirement that it be *rememberable*: it is looked
up by what it is, so it has to be one of the things the language
compares exactly — a number, a character, a string, a truth value, an
enum.  A measured number is remembered by what it measures as well as by
how much, since a metre and a second are not the same key.  Floats are
not excluded by a special rule; they simply are not among the things
compared exactly.

## The Empty One

`⸨⸩` is empty of everything, including of which of the two it is.  It
evaluates to a neutral empty container and a type decides both halves;
a binding with no type is refused, which is exactly what `let f := []`
already does for an array and for the same reason.

This is why the empty case needed no third syntax: Python needs `set()`
because `{}` was already the empty dict, and here neither reading is
privileged, so the type is asked instead of one of them being guessed.

## Order

The entries keep the order they arrived in.  A hash has no order of its
own, and walking one in whatever order the implementation happened to
use makes a program's output depend on something nobody wrote down —
the sort of thing that passes for years and then changes when the
implementation does.  Python arrived at the same place, by a different
route.

## What Is Shared

`#` counts the entries, `∊` asks whether one is there, `[]` reads,
`←` writes, `foreach` walks.  None of that is new: each was already the
one way to ask that question of a container, and a hash and a set
answer them rather than bringing their own spellings.

A hash is looked through by its **keys** — that is what it is asked
about, and what it holds against them is read with `[]`.  An entry is a
key and a value, which is a pair, so `foreach (k, v) := d` names both
halves the way any tuple is taken apart.  That last one needed the
`foreach` variable to accept a destructuring pattern, which a parameter
and a definition already did.

Only what those cannot say is a member: `.keys()`, `.values()`,
`.insert()`, `.remove()`, `.clear()`.

## What Two Sets Make

`∪`, `∩` and `∖` — the glyphs mathematics uses, all three free.

They sit where the arithmetic they resemble sits: `∪` and `∖` where `+`
and `-` do, and `∩` where `×` does.  That is not decoration.  It makes
`a ∪ b ∩ c` mean `a ∪ (b ∩ c)`, which is the reading mathematics gives
it, and it means a reader who knows the arithmetic precedence already
knows this one.

Both operands are the container rather than a stand-in for what is in
it, so they are dispatched before anything can be threaded over one —
the same place `⧺` and `∊` are, and for the same reason.

Two sets make one only where they hold the same type, which is the rule
`⧺` follows for two arrays: what comes out holds one type of value, so
what goes in has to agree on which.  An empty set has no type to
disagree with and takes the other's.

The order is kept, as it is everywhere else a set is walked.  A union
that reordered its result would be the same argument the entries lost:
output that depends on something nobody wrote down.

`⊆` and `⊂` ask whether one is held inside another.  They answer a
`bool`, so they sit with the comparisons rather than with the three
above — what *makes* a set binds tighter than what asks about one, and
what combines the answer binds looser, which is the same shape `<` sits
in.  `⊂` is the proper one: it is false where the two hold the same
things, which is the whole of what "proper" means and the only reason
to have two glyphs rather than one.

No `⊃` or `⊇`.  A superset is the same question with the operands the
other way round, and a second spelling for it would be a second thing
to learn that says nothing new.

## Joining, and Why Only a Hash

`⧺` joins two hashes; a set is refused.

For two *sets* there is nothing for joining to say.  `⧺` on arrays
keeps everything — `[1,2] ⧺ [2,3]` is four elements with the `2` twice,
in order — and that is its meaning.  A set has no room for it: it holds
each value once, so a join would have to drop the repeat, and having
dropped it has computed everything from both, each once, left first,
which is `∪` exactly.  Not equal by coincidence but by construction,
since that is the only thing either could mean.  A second spelling of
`∪` is the thing `⊃` and `⊇` were turned down for.

The two ways to make them differ are both worse.  Answering an *array*
would mean joining two of a kind and getting a third, which no other
use of `⧺` does.  Counting the repeats would mean a multiset, which is
a container the language does not have and which a set is precisely the
one that is not.

A hash is the opposite case.  Two of them joined raise a question that
has a real answer and that nothing else answers: where both hold the
same key, which value survives?  `∪` never faces it, because a set
holds no more about a value than that it is there.  The right-hand one
wins, which is Python's answer for `{**a, **b}` and which makes
`defaults ⧺ overrides` read the way it is written.  A key keeps the
place it first had — what the right operand says is what the key holds,
not where it sits.

## Comparing Two

Order is not part of it.  This is the one place the insertion order
kept for walking has to be *un*-kept: it exists so that a walk is
repeatable, not because a hash has an order, and two that hold the same
things are the same whichever way each was built up.  Making `=` order-
sensitive would have made it answer a question about how the value was
constructed rather than about what it is.

The answer is one truth value for the whole of it.  Two *arrays*
compared with `=` answer element by element, because an array is
threaded over and a comparison is a listable operator; a hash and a set
are the operand rather than a stand-in for what is in them, so they are
dispatched before threading, where `⧺`, `∪` and `∊` already are.

It reaches as deep as what is held, which needed a structural equality
that arrays do not have: `a = b` on two arrays is element-wise and
never answers one bool, so comparing a hash *of* arrays could not be
built out of it.  `assert_eq` had its own deep comparison already and
now knows these too.

## Status

Implemented: literals, `std.hash(K, V)` and `std.set(V)` as types in a
binding, a parameter and a return; homogeneous keys and values;
`#`, `∊`, `[]` read and write, `foreach` over both; the members above;
and the empty one, which a type completes.

Left for later: a hash or a set as a *key* (they are not rememberable,
which is the same question a struct raises), and comparing two with
`=`.
