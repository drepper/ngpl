# Compiling Only What Changed

A design for `--incremental`: a mode in which the compiler writes each
function with room to grow, and on a later build replaces in the file
only the functions whose source changed and those that call them.

This is the design as built.  `src/incr.ngpl` is the whole of the new
code; the two code-generation pipelines call into it at three points
each, and `src/main.ngpl` decides the mode and falls back.

## 1. What the file already says

Two things the compiler already writes make this possible, and neither
was put there for it.

**A digest for every function.**  The bill of materials carries a
`function` row per function, a SHA-256 over the tokens it is written in
— from its first annotation to the last token of its body.  It is over
tokens rather than text, so a comment or a rewrapped line does not move
it, which is exactly the question "did this function change?".

**An address and a slot for every function.**  The symbol table's
`st_value` is where a function's code begins, and `st_size` is *the
distance to the next symbol* — so it already reports the room a
function has, not merely the bytes it uses.  Padding a function
therefore needs no new field: it widens the slot the symbol already
describes.

So a binary already answers, for every function it holds: what it was,
where it is, and how much room it has.  That is the whole of what an
incremental build needs to read back, and `tools/sbom.ngpl` already
demonstrates that reading a section back needs nothing but the file.

One thing had to be fixed for the first of those to be true.  A
method's token range began where its `impl` block began, not where the
method did, so the row scan gave the block's first method a row and the
rest none — 752 rows for 1236 functions, which an incremental build
read as 484 functions it could not tell had changed.  `parse_impl` now
sets `def_start` at each method's own first annotation.

## 2. The shape of the mode

### 2.1 A first build

With `--incremental` and no output file, the compiler compiles as it
always does, and leaves each function `INCR_PAD_NUM/INCR_PAD_DEN` of
its own size in padding behind it — 20%, with a floor of sixteen bytes,
constants in `src/incr.ngpl` and nowhere else.  The padding is filled
with the target's trap byte, so a jump into it stops rather than
wanders.

It is also rounded up to a multiple of sixteen, and that is not
tidiness.  On the five targets whose instructions are all four bytes
wide, a function begins where the last one ended and is aligned because
every function's size is a multiple of four; padding that was not would
leave the next function's first instruction split across a word, which
is not an instruction.  The first build for aarch64 stopped on one
before the rounding went in.

The cost is a larger `.text`.  The benefit is that the next build can
usually write a changed function where the old one stood.

### 2.2 A later build

With `--incremental` and an output file that exists:

1. **Read the old binary.**  Its bill gives a digest per function; its
   symbol table gives an address and a slot per symbol; its `.text` and
   `.rodata` are kept, to copy from.
2. **Digest the new sources early.**  The per-function digests are
   computed straight after parsing — before checking, before any code
   is generated — so the decision is made before the work it avoids.
3. **Decide what to regenerate.**  A function is regenerated when its
   own digest moved, or when a function it names has one that moved.
   The name scan reads the tokens the function is written in, so a
   mention that is not a call counts too — a conservative rule, and
   what the request asked for: the changed functions and their
   immediate dependents.  A qualified name two functions share is not
   trusted for either of them.
4. **Generate only those.**  Every function is laid at the address it
   had in the old file.  A function being regenerated is lowered and
   emitted there; one that is not has its old bytes copied into place.
5. **Write back what differs.**  The file is written whole — the
   compiled subset's file interface has no seek, so patching means
   read, modify, write — and comes out byte for byte what it was
   except in the slots of the functions that were regenerated and in
   the bill, whose digests are what changed.

### 2.3 Three things the mode has to arrange

Each is a place where the compiler decides something from what it
emitted — which a build that copies a function never sees.  Each is
handled by making the decision depend on the parse instead, and each
costs a little size.

**Every literal goes in the image.**  Normally a string is in
`.rodata` only if an emitted instruction reads it.  A build that copies
functions sees none of their reads, so a pool trimmed to what was seen
would drop the strings they name and move every string after them.
Under `--incremental` the pool is the whole of what the source wrote.

**The private calling convention is off.**  It is decided over the
whole program, so it can move for a function whose own source did not,
and a copied function was written against the convention it had.  Under
`--incremental` every function keeps the architecture's own, which no
build moves.

**The runtime is the one the old build carried, in the order it had
them.**  Which routines a binary holds is read off the calls it
emitted.  A rebuild seeds that set from the routines the old file's
symbol table names; a routine this build needs and the old one lacked
still goes in, and moves the ones after it, which the check on the
symbol table then catches.

The order matters as much as the set, and only for the five targets
that share the driver: there a routine is emitted as it is discovered,
in waves, and building its IR is what interns its messages — so the
order it is written in is the order its messages appear in `.rodata`.
Seeding the set puts every routine in the first wave, which is a
different order and so a different `.rodata`, and every rebuild fell
back until the routines were sorted into the order the old file's
symbol table gives them.  x86-64 never had the problem: its runtime is
machine code written out in a fixed sequence, and a routine nobody
reached is skipped rather than moved.

### 2.4 Where the jump tables live

They are at the end of `.rodata`, which is a change this made and kept
for every build, incremental or not.  The reason is that a rebuild has
to keep the old build's tables whole — code copied out of the old
`.text` points into them at the offsets they had — and lay its own
after them.  With the tables last, the old region is exactly from the
computed base to the end of the old `.rodata`, so it can be copied out
without anything recording where it was.  The cost is the tables of the
functions that were regenerated, which stay in the file unread.

### 2.5 Room, and what it is for

Two regions are given more of the address space than they hold, by the
same fifth-with-a-floor rule the functions are padded by:

- **the text region**, so that `.rodata` begins further along than the
  code reaches.  A build laid over another cannot move `.rodata`
  without invalidating every string reference in every function it
  copied, so the room is what lets the code grow at all;
- **`.rodata`**, so that `.data` begins further along than it reaches.
  The read-only data grows at its end whenever a function that owns a
  jump table is written again, since the new table is laid after the
  old ones; without room, that growth crosses a page and moves `.data`,
  and every global reference in the copied code is wrong.

A build laid over a file reserves exactly what that file reserved --
`.rodata`'s address minus the text's, and `.data`'s minus `.rodata`'s,
both read back from the section headers.  A first build reserves the
fifth.  A plain build reserves nothing, and its output is byte for byte
what it was before any of this.

The rooms are worked out in code generation, not in the ELF plan, and
the plan is told: code generation patches the address of every string
and every global into the instructions, so it is the one that has to
decide where those live.  Two copies of that arithmetic is one copy too
many -- there were two, and the second was wrong the moment the first
reserved anything, which cost a segmentation fault to find.

### 2.6 Where a function goes when it will not fit

The text region is `.text` and, after it, one section for each build
that had to move a function out — `.text2`, `.text3`, and so on, each
loaded, executable and not writable, all of them one mapping and one
buffer.  The section headers are the only thing that divides them.

A function that will not fit where it stood is written there instead.
Its old slot stays where it is, filled with traps, and nothing is left
behind at the old address: **no trampoline is needed**, because a
function that names one that moved is a function this build writes
again, and it calls the new address.  That is the rule about immediate
dependents earning its keep — it was a margin when every function
stayed put, and it is what makes moving one safe.

A function already out there is written where it is, in the order it is
in, since code that calls it and was not written again calls it there.
If it has outgrown even the room it was moved into, it moves again,
into this build's own section.  Each moved function is left the same
fifth of padding a function in `.text` gets, so the build after this one
can usually write it again where it now stands rather than moving it a
third time.

Three things this asks of the rest of the compiler:

- **The emitter can be rewound.**  Whether a function fits is only
  known once it has been written, so it is written into its slot,
  measured, and — where it overran — unwritten: `Emit.mark` records the
  length of every list the emitter appends to past the end of a
  function, and `Emit.rewind` truncates each back to it.  The
  per-function lists need no such thing, since a function empties them
  before it ends.
- **What it calls is found out before the runtime is written.**  Which
  runtime routines a binary carries is read off the calls that were
  emitted, and the set is closed and the routines written before the
  overflow is.  So the calls of a function bound for the overflow are
  harvested from the emission that measured it, and kept until the set
  is built.  A function already out there and unchanged needs no
  harvesting: what it calls, the previous build carried.
- **The symbols and the backtrace table are in the order the code is
  laid out**, not the order the functions were parsed in.  A symbol's
  size is the distance to the next symbol, so a moved function is left
  out of the run of program functions and added after the runtime's
  own, which is where it is.  The backtrace table is handed the same
  order, and two ends rather than one: where the program's own code
  stops, and where the whole region does.

### 2.7 What must hold, and what may change

The invariant is not that the file comes out the same.  It is that
everything the copied code names is at the address it named:

| Must hold | May change |
|---|---|
| every function at the address it had, inside the room it had | the bytes of any string: nothing points into the middle of one |
| the descriptors and every table after them, byte for byte | the value of a global that is never written |
| the symbol table, name for name and address for address | the digests in the bill |
| `.rodata` no larger than the room the file reserved | its length within that room |
| every symbol at the address it had | one this build moved, which is out past everything the last build used |
| no symbol's slot smaller than it was | a slot that grew, which is what the hole a moved function left does to the one before it |
| | the table a backtrace reads, which is layout written down as data |
| `.data`, byte for byte | |

The descriptors are what makes the second row checkable in one pass:
each says where a string begins and how long it is, so comparing
`.rodata` from the descriptors onward checks every string's offset at
once.  A string that changed length moved either the descriptors or the
strings after it, and either way what follows will not match.

That a string's own bytes may differ is what makes the mode useful:
`@pre` names the line it is written on, so adding a line above it
changes that message.  The address does not move, the copied code
prints the new message, and the new message is the true one.

### 2.8 When it does not line up

Incremental compilation is an optimization, and an optimization that is
ever wrong is not one.  Each of these makes the build fall back to a
whole one, which is always correct, and says which:

| Condition | Why |
|---|---|
| a function is new, or one is gone | it has no slot, and the layout would shift |
| the text grew past its room | `.rodata` begins where that room ends |
| a symbol the old file had is missing, or one is new | the layout is not the same layout |
| the read-only data came out different past the strings | a literal, a table or a global moved, and every reference to it |
| `.rodata` grew past its room | `.data` begins where that room ends |
| `.data` came out different | a global's initial value or its place moved |
| the runtime routines needed changed | the code after the functions is not the same code |
| the target, the class or its flags changed | the file is not a variant of the old one, and its code is another machine's |

A whole build under `--incremental` writes fresh padding sized to the
new functions, so the build after a fallback is incremental again.

### 2.9 What is deliberately not built

**Moving the unloaded content to make room.**  What follows the loaded
sections in the file — the symbol table, its strings, the section
headers — can be pushed further out at no cost.  But it does not answer
the question it looks like it answers: a function needs room at a
particular address inside the text region, and what is in the way there
is `.rodata`, not the symbol table.  Room is made instead by reserving
it, before anything needs it (§2.5), and a function that will not fit
goes into a section of its own inside that room (§2.6).

**Global variables.**  A global's address is its offset in its segment,
settled by the order and sizes of the globals, which come from checking
rather than from emitting — so while the declarations are unchanged the
addresses are unchanged and nothing more is needed.  A read-only
global's *value* may change in place, since its address has not moved.
A writable one's initial value may not, yet: `.data` is compared byte
for byte, and relaxing that wants an argument about its layout that
the read-only side gets from the descriptors and the writable side has
nothing to get from.

## 3. The invariants

Two checks hold the mode to its promise, and both are cheap.

**Every function lands where it was, or in a section of its own.**  The
emitter is told each function's old address and pads to it.  One that
would overrun the next address is caught there rather than discovered
later — and written out past everything the last build used, where its
callers, which are written again whenever it is, will call it.

**Nothing else moved.**  After code generation the new `.rodata`, the
new `.data` and the new symbol table are checked against the old, as
§2.7 sets out.  This is what makes it safe to have skipped emitting
most of the program: whatever the skipped functions would have
contributed to those tables, they contributed before, and the tables
are the same.

## 4. What it costs and what it saves

A rebuild still lexes, parses, checks and lowers the whole program:
this is not separate compilation, and a change anywhere can change what
checking says anywhere.  Lowering happens even for a function whose
code is copied, because lowering is what puts a string literal in the
pool and the pool is what `.rodata` is.  What is skipped is emitting,
and the writing of the parts of the file that did not change.

On the compiler's own sources — 1236 functions, twenty-five files —
that is not yet a saving worth measuring: a whole build takes 0.71 s
and a rebuild with nothing changed 0.73 s, since reading a
two-and-a-half-megabyte binary back and comparing it costs about what
emitting cost.  The time is in the phases the mode does not skip.

What it buys today is a file that changes only where the program did.
A one-line change to one function writes two functions again — the one
that changed and the one that calls it — and moves two bytes of
`.text`, the rest of the difference being the digests that say so.  A
change that outgrows a function's slot writes it into a section of its
own and leaves the rest of `.text` alone.  That is what makes a rebuilt
binary comparable with the one before it, and it is the ground a
smaller front end would be built on.

`--log=json` says what it decided:

```
{"decision": "incremental-first", "functions": 1236}
{"decision": "incremental", "read": "build/ngplc", "functions": 1236, "regenerated": 2}
{"decision": "incremental-fallback", "why": "'twice(i64) → i64' outgrew the room it had"}
```
