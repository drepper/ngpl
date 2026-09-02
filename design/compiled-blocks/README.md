# Compiling Blocks to Python Inside the Interpreter

The bootstrap interpreter walked the tree.  It now compiles each block
of statements to Python source the first time the block runs, and runs
that.  This is the design, what it is held to, and what was measured.

## 1. Why: the cost was the walk, not any one thing in it

The only workload worth measuring is the compiler compiling itself
(`python -m interp src/main.ngpl -- src/main.ngpl -o x`, 37 files,
~925 KB).  Sampled every 2 ms over the whole run, the profile is flat:

| where | share |
|---|---|
| `eval_expr` itself: reading the node's class, writing its position, the dispatch | 13% |
| unwrapping optionals on the way into every operator | 8% |
| environment lookups | 7% |
| `_reachable_ids` under `_check_borrowed_answer` | 7% |
| per-statement lifetime bookkeeping (`_after_last_use`) | 6% |
| constructing values (`IntValue`, `none()`, `mk_bool`) | 5% |

No handler is hot.  What the walk did 846 million times -- look at a
node, decide what it is, write down where it is, call the thing that
knows -- is where the time went, spread over every node.  The counts
(one run, every node the evaluator met):

```
expressions 846,221,128     statements 153,522,271     calls 23,762,781
  40.2%  VarRef                  36.7%  IfStmt
  23.2%  BinOp                   26.5%  ExprStmt
  11.0%  GetAttr                 20.7%  VarDef
   9.4%  IntLit                  11.2%  assign
   5.4%  Subscript                1.4%  ForEachStmt
   3.8%  MethodCall               1.3%  ReturnStmt
   2.5%  UnitExpr                 1.1%  WhileStmt
   1.3%  FuncCall
```

Eight expression kinds are 97% of expressions; four statement kinds
are 95% of statements.  That is what a compiler has to cover, and the
rest may go the slow way without anyone noticing.

## 2. What: the walk, written down once

`Evaluator.eval_stmts(stmts)` is the one place every block of the
program passes through -- function bodies, loop bodies, the arms of an
if and a match -- so it is the one hook.  The first time a list of
statements arrives it is handed to `interp/compile.py`, which emits
one Python function for it, `def block(ev, K)`, compiles and `exec`s
the source, and caches the result against the list.  Every later
arrival runs the function.

The function does **exactly what the walk did, in the order the walk
did it**.  For each statement: the watchdog tick, the position written
to `_last_pos` and the top of the call stack, the temporaries scope
opened and closed, the return sentinel re-raised, the discarded-lambda
warning, and the lifetime bookkeeping.  Then the statement's own work.
What differs is that everything the walk found out by looking is
already written into the source:

- which handler a statement wants is a constant, not a dictionary probe
  on the node's class;
- an `if` is a Python `if`, its condition inline, each arm a call back
  into `eval_stmts` (which is compiled in turn);
- a `return` raises the sentinel with its value inline;
- an expression statement's expression is inline;
- and `_after_last_use`, which asked the block's last-use table at
  every statement, is emitted only at the statements where it would
  have found something, with the names it would have found.

Expressions are emitted as Python expressions calling small helpers
on the evaluator -- `_c_var2`, `_c_iop`, `_c_call`, `_c_getattr`,
`_c_sub_index`, `_c_method`, `_c_unit` -- each the second half of the
handler it came from, with the first half (evaluate the children) done
inline by the generated code.  A handler was split rather than
duplicated, so the walk and the compiled form share the rule.  An
integer literal is boxed once at compile time and referenced as a
constant.  Anything the compiler does not know is `ev.eval_expr(node)`
or `ev._eval_stmt(stmt)`: **the fallback is per node**, so the whole
program is compiled from its first statement and coverage grows a
kind at a time with no cliff.

## 3. What it is held to

**The evaluator is the definition.**  A compiled block that does
anything the walk would not is a bug in the compiler, and there is no
allowance for a faster answer that differs.

**Byte identity** is the gate: the compiler compiled under the two
must be the same binary.  It is stronger and faster than the suites,
and every version below passed it.  The suites run too, because they
pin what the binary cannot: the wording and position of every
diagnostic, the REPL, the backtraces.

**Positions are the subtle part.**  The walk writes every node's
position as it enters it, and what a diagnostic or a backtrace then
shows is *the position of the last node entered*.  That is not the
position of the node that failed -- a call's backtrace line names the
call's last argument, not the call -- and the first compiled version
got exactly this wrong.  The rule the compiler follows: a node writes
its position where the walk would, in the walk's order, unless
whatever follows will write its own first and nothing can fail in
between.  So a literal under a binary operator writes nothing (the
operator writes its own position again after its operands), but a
literal that is the last argument of a call does.  The `observable`
flag in `_Emit.expr` is this rule.

**Identity of a block is the list itself.**  The cache is keyed by
`id(stmts)` and holds a reference to the list, so a compiled list is
never collected and its id never reused.  The first version held only
the id; the REPL, which makes a fresh list per line, ran a dead
line's code.

**`NGPLI_INTERPRET=1`** turns compilation off.  It exists for the A/B
and for finding out which of the two an odd result belongs to.

## 4. What was measured

Wall time of the self-compile, one run each, on the same machine:

| version | wall | over the walk |
|---|---|---|
| the walk (baseline, 2 ms sampler attached, ~1% of it) | 1258 s | -- |
| v1: statements compiled, hot expressions via helpers | 1177 s | 6% |
| v2: field access, subscript, method call, unit inline | 1151 s | 9% |
| v3: variable-read and integer-operator fast paths | 1133 s | 10% |
| v3 + `_reachable_ids` no longer copying every array it meets | 1045 s | 17% |
| v4: statement-form emitter; reads, operators, `while` inline | 1030 s | 18% |
| v5: `let` initializers, assignment right sides, method calls under modules, `and`/`or` | 926 s | 26% |
| v6: the plain `foreach` turn inline | 909 s | 28% |

| v7: the planned call | 907 s | -- |

Timing is noisy (±3%); a difference smaller than that is not one.
Every version produced the identical binary.

**The table above overstates the walk.**  Those runs overlapped other
runs on the same machine, which cost the walk more than it cost the
compiled versions.  Measured clean -- the walk and v7 back to back,
nothing else running -- the walk takes **1191 s** and v7 **907 s**:
24%, or 1.31 times.  The per-version deltas in the table are real in
their direction and unreliable in their size; only a back-to-back
pair on an idle machine says how much.

Two lessons in that table.  Ten percent (v1--v3) is what taking the
dispatch out of a tree-walker buys when every node still calls a
helper.  Then v4 -- reads and operators inlined as statements, which
should have been the big one -- bought nothing measurable, and the
profile said why: two thirds of all expressions were still entering
the walk, through the `let` handler evaluating its own initializer,
the assignment evaluating its right side, and every method call
falling back because the program declares modules.  Compiling those
(v5) was worth as much as everything before it.  **What matters is
which nodes reach the compiled path at all, not how tight the
compiled path is**; the histogram of what falls back is the thing to
read before optimizing anything.

Where it stands after v6, at leaf: unwrapping optionals 6%, boxing
values 5%, the watchdog 2%, then the checkers -- `coerce_to_type`,
`check_int`, `_check_return_type`, units -- each around one percent.
That is the semantics, and the walk's own share is under ten.

## 4a. Cheaper checks, and where that ended

After v7 the profile is the semantics itself, so the next round went
at the checks: the range of every named width worked out once instead
of shifted out per `check_int`; `resolve_width` and
`Unit.stands_in_for` memoized (a unit's components and decay never
change after its declaration, so neither does the answer);
`unwrap_optional` and `_unwrap_operand` answering for three more
types before the isinstance ladder; the builtin byte and ptrdiff
units hoisted out of `_check_index_unit`; the integer fast paths of
`+ - ×` skipping two call layers; the comparisons answering two plain
integers before unwrapping anything.

Worth about two percent all told -- 907 s to 893 s -- and the second
half of it (the comparisons) measured as nothing.  That is the
signal to stop: the remaining per-operation work is boxing a result
and probing one or two dictionaries, and no exact shortcut is left
that skips either.  Clean pair after this round: **the walk 1191 s,
compiled 893 s, 1.33 times**, identical binaries throughout.

## 4b. The match, and the compiler's own work

By 2026-09-01 the compiler had grown to 1.6 MB of source from the
925 KB the table in §4 was measured on, and its dispatch had been
rewritten: `check_expr`, `check_stmt` and the lexer's byte classes
are `match` statements over enumerations rather than `if` chains,
and every token kind, node kind and opcode is an enumerator rather
than a number.  The sampled self-compile took **1806 s**, and the
sampler put 31% of all samples under `_eval_match_by_enum`.

The match was a walk down the arms -- `arm.kind`, a string compare
of the enumeration's name, a dictionary probe for the member's value,
per arm, per execution -- and `_eval_match` scanned the arms twice
more before that to decide which kind of match it was.  Now the kind
is read off the arms once and kept on the node, and an enum match
keeps a table on the node from member value to arm, built the first
time it runs against the enumeration it saw: one probe, whatever the
arm count.  `MatchStmt` has a compiled form too, so the subject is
evaluated inline and only the probe is a call.  Beside it, the
enumerator went into the fast type lists of `unwrap_optional` and
`_unwrap_operand`, two enumerators compare at the top of `_op_eq` and
`_op_neq` without being unwrapped, and `.ord()` on one answers at the
top of `_call_method` before the ladder.  Units, which the lexer's
byte arithmetic carries everywhere, keep their dimension as one
precomputed tuple, so `same_dimension` and `__eq__` compare that
rather than building two dictionaries, and a conversion to the unit
a value already carries returns the value rather than dividing two
fractions to find a ratio of one.

Sampled self-compile, same source, same machine, one run each:
**1806 s → 1604 s**, 11%, identical binaries.  The match's own
dispatch was the visible part; what stayed under it was the arm
bodies, which is the checker's work.

The larger finding was in that work.  Timed natively the compiler's
own name lookups -- `fn_index`, `fn_in`, `global_index`,
`struct_index`, `enum_index` -- were a walk down every function in
the program at every call site, `fn_in` building a `module.name`
string per candidate as it went.  Under the interpreter each turn of
that walk is a handful of statements, and the compiler resolves tens
of thousands of names.  They are hash tables now (`names.ngpl`, the
table the incremental build already had), and the IR columns a
function leaves behind are cut with one slice each rather than pushed
element by element.  Native self-compile: **1.14 s → 0.80 s**.  Interpreted, as
the bootstrap's stage 1 runs it (no sampler): **1318 s**, against
the 1604 s the sampled run of the old source took a moment before --
about 17% from the compiler's own work, and **1806 s → 1318 s**, 27%,
for the round as a whole.  Identical binaries throughout, and the
fixed point holds.

**A rule that came out of it:** what the interpreter runs is the
compiler's algorithms, and a quadratic walk in the compiler costs the
interpreter a thousand times what any per-node shortcut recovers.
Read the compiler's hot functions before reading the interpreter's.

## 5. What is next, in the order it pays

1. **`_reachable_ids`** (7%): every call answering an array or a
   struct walks everything reachable from every argument to decide
   whether the answer must be copied.  This is not the walk's cost and
   the compiler does not touch it; it wants its own fix.
2. **Names as Python locals** -- reconsidered.  After v4 a read is
   one dictionary probe on the innermost frame plus the frozen-table
   probe; a slot would make the first an index and leave the second.
   Every helper that looks a name up by string (`_end_scope`, the
   lifetime tables, the frozen table) would have to be taught for a
   gain the profile no longer shows.  Not worth it now.
3. **The call** -- done in v7.  `_make_plan` reads a function's
   signature once: no pack, no generic, no condition, no borrowed
   answer, every parameter a plain name, and what each parameter's
   type measures.  `_call_planned` is then the walk's call with the
   settled things read off the plan and the steps that would do
   nothing not taken.  A plan holds while the alias table is what it
   was (`_ALIAS_VERSION`), since what a type measures is read off that
   table.  The sampler attributed 19% of all samples to the call's
   prologue and epilogue before this; what remains of it is the work a
   call has to do -- copying by-value arguments, coercing them, the
   return check, `_end_scope`.
4. **Loops** are inline in their plain form (v6); `while` with a
   bound name, `foreach` with several names or a typed one, and
   `match` still go to their handlers.
5. **Functions as one Python function**, control flow and all -- the
   transpiler proper.  Everything above is on the way to it; by then
   the semantics are factored into helpers that generated code can
   call, which is the part that is hard.
