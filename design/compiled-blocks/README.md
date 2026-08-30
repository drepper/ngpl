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

Timing is noisy (±3%); a difference smaller than that is not one.
Every version produced the identical binary.

Ten percent from compiling is what taking the dispatch out of a
tree-walker buys when every node still calls a helper: the helper is
a Python call, as the handler was, and the work inside it -- the
frozen-name checks, the environment probe, unwrapping an optional,
boxing an integer -- is the same work.  The rest of the way is §5,
and each step there is measured against this table.

## 5. What is next, in the order it pays

1. **`_reachable_ids`** (7%): every call answering an array or a
   struct walks everything reachable from every argument to decide
   whether the answer must be copied.  This is not the walk's cost and
   the compiler does not touch it; it wants its own fix.
2. **Names as Python locals.**  A function's `let`s and parameters
   could live in a list indexed by slot, resolved at compile time,
   with the environment kept for globals and captures.  Every helper
   that looks a name up by string (`_after_last_use`, the frozen
   table, `_end_scope`) has to be taught, which is why it is not done
   yet.
3. **Loops inline.**  `while` and `foreach` are still the walk's
   handlers with compiled bodies; the per-iteration frame push, loop
   label and break/continue signals could be emitted.
4. **Functions as one Python function**, control flow and all -- the
   transpiler proper.  Everything above is on the way to it; by then
   the semantics are factored into helpers that generated code can
   call, which is the part that is hard.
