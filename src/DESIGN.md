# ngplc — Attempts 2 and 3 of the Self-Hosted Compiler

The design record for the second attempt, written in the bootstrap
subset of NGPL and run by the Python interpreter.  Attempt 1 is
archived under `old/attempt1/` with its own DESIGN and ANALYSIS; this
attempt grows the compiled language from core-0 to **core-1** and
adopts the project's control-flow policy end to end.  What this
attempt proved and where it stops is in `ANALYSIS.md` beside it.

## What This Attempt Compiles

**core-1**, a strict subset of NGPL, to static x86-64 Linux ELF
executables using only the kernel's syscall interface.  A core-1
program means exactly what the bootstrap interpreter says it means;
anything outside is refused by name — including the bootstrap's
reserved words, which attempt 1 wrongly accepted as identifiers.

Over core-0, core-1 adds:

- **the sized integer family** `i8…i64`, `u8…u64`: untyped literals
  adopt the width of what they meet (with exact folding of literal
  arithmetic and range checks at adoption); mixed signedness is
  refused; same-signedness widths widen to the wider side.  Checked
  arithmetic aborts on leaving the range at every width, `@wrap` masks
  and re-extends, shifts wrap with the count held below the type's
  value bits, division truncates toward zero, ordering and division
  are signedness-aware, and u64 prints past the signed range.
- **units-lite**: `¤ptrdiff` and `¤byte` on integer bindings and
  parameters, carried through arithmetic per the spec's scalar rules;
  `#` answers a measured count (`¤byte` for `u8[]`, else `¤ptrdiff`)
  and a subscript must carry the array's measure, untyped literals
  exempt.
- **arrays** `T[]` of integer elements: born from a literal, grown by
  `push`, indexed with bounds checks, walked by `foreach`, handed
  around by `&`/`&mut` borrow (written `&name` at the call, as the
  bootstrap has it), with `pop()`/`get(i)` answering through `?? d`.
- **strings** as values: literals, variables, parameters, returns,
  `⧺`, content equality, `#s` counting characters (lead bytes), and
  printing.
- **globals**: constant-initialized scalars, immutable ones read
  anywhere, `mut` ones an effect behind `@impure`.
- **`std.implementation`**: `name`/`language`/`interpreter`/`compiled`
  folded to constants about ngplc itself, so one test suite serves
  every implementation.

Attempt 3 grows core-1 to **core-2** with structs:

- **structs** with fields of every core scalar kind plus strings and
  arrays; literals `Name{f: v, …}` checked complete; field reads and
  `x.f ← v` stores; `impl` blocks whose methods take `&self` or
  `&mut self` (a method is a function named `Name.m` with the receiver
  first) or no receiver at all (a static, asked of the struct's name).
  A struct value is a pointer to an allocated block of one slot per
  field.  The subset keeps ownership trivial: a struct binding is born
  from a literal or a call and rebound only to another fresh one,
  travels by `&`/`&mut` borrow, and is returned only freshly built —
  aliasing cannot arise, so value-versus-reference semantics cannot
  diverge from the bootstrap's move-and-borrow rules.  A struct may be
  declared below whatever names it (the parser pre-scans the token
  stream for struct names in one sweep).  `&mut self` methods and
  field stores demand a `mut` binding or `&mut` parameter, fields
  inheriting their holder's mutability.
- **optionals** `T?` of any scalar or struct, with `⊨(v)`, `∅`,
  `match` over the two shapes (the bound name scoped to the present
  arm, a trailing match handing each arm's value on as the function's
  answer), presence as truthiness, comparison with `∅` (and only ∅ —
  content comparison waits), and `??` generalized to every optional.
  The representation makes absence free: an optional is a pointer,
  `∅` the null one and `⊨(v)` a box holding the value, so a presence
  test is one compare against zero, `= ∅` needs no special lowering
  at all (∅ is the constant 0), and nested `⊨(∅)` falls out naturally.
  `⊨` allocates, so it is not speculatable; `∅` is.
- **arrays of structs** `S[]`: the element is the struct's pointer, so
  the array machinery carries over unchanged; `v[i].f` reads and
  stores, whole-element replacement by a fresh literal, `&`-borrowed
  walks, and an element's own array growing through `v[i].items.push`.
- **dictionaries** `std.dict(K, V)` — K a plain integer type or `str`, V any
  core scalar, `str`, or struct: born from a typed literal
  `⸨k: v, …⸩`, read by `h[k]` answering `V?` (absence composes with
  `??` and `match` for free), written by `h[k] ← v` on a `mut` binding
  or `&mut` borrow, asked by `k ∊ h` and measured by `#h`; handed
  around by borrow like the other containers, never copied, reassigned
  or returned.  The type packs as `8192 + ki×2048 + V` with `ki`
  encoding the key's width/signedness or str-ness — a band disjoint
  from the arrays' `4096 + elem` (elements stay below 4096), so each
  `ty_is_*` predicate answers alone, in any order.
- **tuples** `(T1, T2, …)` of plain integers, truth values, strings,
  structs and optionals: built by a literal whose type the binding or
  the enclosing return states, handed back by functions and methods,
  taken apart by `let (a, b) := …` (`_` discarding, `mut` naming
  changeable parts, a stated `: (…) =` type welcome), asked by a
  written-out index `t[0]` and counted by `#t` — both settled at
  check time, so the index is a field load and the count a constant.
  The representation is the struct's: a pointer to one slot per
  element, `IR_SNEW`/`IR_FSTO`/`IR_FLD` reused whole, zero new IR ops
  and zero new runtime code.  Shapes intern into a table in the Ast
  (band `26624 + tidx`), so type equality stays one integer compare.
  A tuple travels by value and never by parameter, borrow, global,
  optional, array, dictionary or struct field — each refused by name.
- **width suffixes** `7i64`, `200u8`: the lexer closes the literal's
  type (the code rides in the token as `big + 2×type`), the checker
  adopts it through the same range check as contextual settling.  The
  bootstrap requires them inside tuple literals in return position,
  so the shared subset now has them everywhere.
- **characters** `char`, a Unicode scalar value in a slot: literals
  `'a'`/`'λ'`/`'\n'`/`'\u{1F389}'` lex as closed-type tokens on the
  same `big + 2×type` ride as a suffix; `.chr()` crosses from any
  integer (three refusals — negative, past 0x10FFFF, surrogate —
  folded on literals, two cold never-taken branches at run time) and
  `.ord()` crosses back to `u32` for free; `s[i]` answers the
  character at a ¤ptrdiff position and `.chars()` lays a string out
  as a `char[]`, both over real UTF-8 in the runtime; `foreach` walks
  a string's characters; `⧺` joins characters into strings; the six
  comparisons order by code point through the ordinary signed path
  (code points stay below 2^21).  Character arrays and tuple elements
  ride the existing machinery; dictionaries of them wait.
- **struct values travel**: the bootstrap's structs are references —
  every probe shows one struct behind however many names — and the
  compiled pointer representation is the same thing, so structs now
  pass by value as parameters, return from any expression, and a
  read-only binding may name a struct held in an array element, a
  dictionary, a tuple, an optional or another binding, all with zero new
  code.  The discipline that remains: a `mut` struct binding and a
  struct reassignment must be born fresh (a literal or a call), so a
  let whose right side visibly names shared data cannot create a
  mutable alias; `&mut` stays the way to change what is shared.  (A
  call may still answer a shared struct — the reference semantics
  make that identical in both implementations.)
- **`:=` inference**: `let x := e` and `let x : mut = e` take the
  binding's type from a right side that states it — a call, a
  suffixed or self-stating literal, any settled expression — while
  what states nothing is refused with the stated-form cure spelled
  out (`settles on 'int'; state a sized type, as 'let x : i64 = …'`).
  The per-kind birth rules ride along unchanged: dictionaries and arrays
  are still born from their literals, a mut struct binding still
  born fresh.
- **what self-hosting asked for**: containers travel like structs do
  (arrays and dictionaries as by-value parameters and returns — the same
  reference-semantics argument, the same non-mut discipline on
  bindings); structs may hold structs, and a store reaches through
  any postfix path (`self.a.nkind[id] ← v` — the statement parser now
  parses the expression first and turns a following `←` into the
  store its shape names, retiring the old name-only target ladder);
  `@dropunit` passes a measured number through unmeasured; and an
  immutable global dictionary or array of constants is built by a
  synthesized init function the image runs before `@start` — the two
  runtime-initialized global kinds, because the compiler's own keyword
  and glyph tables want the one and its opcode tables the other, and a
  table read on every operation is better read from a global than
  rebuilt by the function that reads it.
- **the OS surface `main` stands on**: `std.args.all()` (argv[1..] as
  a `str[]`, the kernel's argc/argv captured at the entry rsp into
  the data segment), `std.fs.cwd().open_file(p)` answering `File?` so
  absence composes with `??` and a `@noreturn` default, `has_file(p)`
  answering whether a name is a plain file without opening it (one
  statx, no descriptor, so a resolver that tries many names pays for
  the one it finds), `file_id(p)` answering `(device, inode)` from the
  same statx — `(0, 0)` where nothing is there — so a reader knows
  which file a name is before it opens it, `create_file`
  aborting rather than answering, `read_file` (fstat + read loop +
  widening into slots), `write` (narrowing + write loop), `close`,
  and `std.arena.allocator()` as an accepted token — the bump
  allocator is the arena.  `@start` may answer a plain integer, which
  `_start` hands to `exit`.  Unit-suffixed literals (`1¤ptrdiff`,
  `0¤byte`) close their type at the lexer like width suffixes, and
  `byte` names `u8`.
- **finding, holding, slicing**: `container ⍳ wanted` answers the
  position as an optional ¤ptrdiff (string elements compared by
  content), `⊞ ⊟ ⊠` hold arithmetic at the type's edge — narrow
  widths compute exactly in 64 bits and clamp by compare, the full
  width reads the flags the op leaves, the saturation target chosen
  by the operands' signs before the flags matter, selects throughout
  and never a branch — `⊕ ⊼ ⊽` finish the logic family as one
  bitwise op and at most one xor, and `v[a…b]` takes a fresh
  sub-array, both ends included, `hi < lo` empty, an end outside the
  array out of range.
- **sized arrays and ⍴**: `T[n]` makes the length part of the type
  (shapes interned like tuples'), a literal or a written-out `n ⍴ x`
  must state exactly that size, push and pop are refused by name, and
  a slice of one answers a dynamic array.  `n ⍴ x` fills n copies of
  a scalar or cycles an array's elements to the count (`rt_afill`,
  `rt_acyc`); a matrix reshape is refused by name.  Truth values join
  the array elements, a by-value parameter may be `mut` (its slot
  changes, the caller's value does not travel back; a mut container
  still asks for `&mut`), and `@start` no longer demands `@impure`
  for itself — every effect inside asks on its own.
- **array joining**: `a ⧺ b` joins two arrays of one element type at
  the outermost dimension into one fresh array (`rt_acat`), the
  binding's array type reaching both sides so a bare literal operand
  settles where it stands.  A join is a fresh birth, so a mut array
  binding may be born from one — or reborn: a mut array now takes any
  fresh array on reassignment, `x ← x ⧺ […]` included.  A bare `∅`
  as a unit body is the nothing it names.
- **while bindings**: `while x := e:` evaluates `e` afresh each
  turn, loops while it answers a value, and `x` names the value
  inside the body — an optional-answering call unboxed by the loop's
  own test, or `pop`, whose emptiness is the test (no boxing at all:
  one length check, then the pop).  `get` is refused by name — it
  answers the same place every turn.
- **iterators**: `v.iterate()` answers a two-slot box — the array
  and a position — and `it.next()` steps it: position under length
  answers the element and advances, the end answers ∅, the length
  read fresh each step so the walk is live against the array, as the
  interpreter's is.  next() is taken with `??` or a while binding
  (which steps it with no boxing at all); an iterator's type is
  interned by element and written by no syntax — it lives only in
  inferred locals.  Zero new IR, zero new runtime.  `std.bytes(s)`
  answers a string's bytes as a `u8[]`.
- **comptime introspection**: `@typeof(e)` folds to the type's
  spelling as a string constant — for exactly the types whose
  spelling is the type's alone (scalars, structs, chars, tuples,
  sized arrays); a dynamic array's or optional's spelling carries the
  value in the bootstrap (`i64[1]`, the unwrapped inner), so those
  are refused by name.  `static_assert` and `static_assert_eq` are
  judged as the file is checked — constant operands only, a failure a
  diagnostic, the statement emitting nothing.  The while binding
  gained its other spellings (`while x : T = e`, int and bool
  conditions looping on truthiness, `get` and discarded `pop` as
  unwrapping contexts); its `mut` form means writing back through a
  borrow, which core-2 loops do not hand yet, and says so.
- **write-through element references**: `foreach x := &v` and
  `&mut v` lend the elements — the binding's slot holds the
  element's address (`IR_AREF`, a bounds-checked `lea`), a read of
  the name reaches through it, and assignment stores back through
  into the array; `&` refuses the store, `&mut` of an immutable
  binding is refused at the borrow.  `while e : mut = it.next():`
  hands the same reference from an iterator, so a loop can raise
  every element in place.  `@typeof` of such a binding spells the
  reference (`&mut i32`), and a bare type name in a static assertion
  stands for its own spelling.  Struct elements are refused by name:
  they are already shared, and their fields change in place.
- **directory objects**: `std.fs.cwd()` alone is a value of its own
  type (the `.open_file`/`.create_file` chains keep their old path),
  and `dir.iterate()` answers an iterator of entries, each a
  two-slot `{name, type}` block.  The walk itself is one runtime
  helper (`RT_DENTS`): `openat` on a stack-built `".\0"` (the rodata
  interns strings without terminators, so the path is spelled in
  place with a `push`), a `getdents64` loop parsing the kernel's
  records where they lie, `"."` and `".."` left out, the order the
  directory's own.  `e.name` and `e.type` are field reads; the
  `std.filetype.*` names fold to the `S_IF*` constants from
  `<sys/stat.h>`, as the interpreter holds them — the kernel's
  `d_type` is that value shifted right twelve, so the walk stores
  `d_type << 12` and the mapping costs one instruction.  The
  constants and `e.type` share a `filetype` type of their own
  (`TY_FTYPE`): it compares with itself and with untyped literals
  (which meet it by value, as the interpreter's enum does), has no
  order, spells itself for `@typeof`, and refuses printing by name
  — the interpreter prints the enumerator's name, which the subset
  does not carry.  Reading a directory writes nothing, so neither
  `cwd()` nor `iterate()` wants `@impure` — only opening and
  creating files do, as in the interpreter.  `next()` outside an
  unwrapping context now answers the boxed optional (a step is
  `SNEW`+`FSTO` like any `⊨`, the end the null), and optionals of
  int, bool, char and str bases compare with their own kind and with
  `∅` — presence bits first, contents only when both are there;
  struct bases are still taken apart by `match`.
- **matrices**: rank 2 and rank 3, an outer dynamic array whose
  elements are row descriptors (rank 2) or plane descriptors (rank 3) — every sharing rule falls out of the existing array
  runtime with no new IR and no new runtime helpers.  Types
  `T[,]`/`T[r,c]`/`T[,c]`/`T[r,]` intern into an Ast-owned table
  (element, two extents, ⁻1 open); the ref packing's multiplier
  moved from 65536 to 262144 to clear the band.  Rows have a type
  band of their own (7168+elem, inside the dynamic arrays' range):
  they read as arrays everywhere but refuse `push`/`pop` — a
  matrix's row keeps its length, as the interpreter's extent-locked
  values do.  `m[i, j]` desugars in the parser to the chain
  `m[i][j]` (rows alias, so the chain is the pair); `m[i, a…b]`
  narrows a row into a fresh array (`ASLICE` copy), `m[a…b]` keeps
  the matrix type with the row count opened (same rows, `ASLICE` on
  descriptors).  `m[rows, cols]` cuts both ways at once and answers
  a matrix; `m[rows, i]` answers one element from each row, which
  is an array, a column not being a matrix.  Neither can hand back
  rows the matrix already holds, so both build every row of what
  they answer and share nothing with what they were cut from --
  where a range of rows alone shares, which is the distinction the
  spec draws and t53 pins by writing through the original.  Both
  lower to one walk over the chosen rows, cutting each with the
  slice the runtime already had.  A tuple-shaped `⍴` builds the flat rank-1 cycle
  (the cycle runs across the row seam) and cuts rows with an
  emitted `ASLICE` loop; extents are written-out numbers, checked
  statically, so no runtime shape aborts exist.  `.shape` is
  `[#m, #m[0]]`¤ptrdiff, safe because a matrix is never empty.
  Literals check row-by-row against the stated type (ragged and
  wrong extents refused with the counts); `⍴` and literals are the
  only births.
  A rank-3 shape (`T[,,]`, `T[p,r,c]` and every partly-open kin)
  adds a third extent to the same table plus one field the table
  did not need before: **the type one subscript answers**, a row
  for a matrix and a matrix for a cube.  It is settled inside
  `mat_intern`, where the table may still grow, because the two
  `elem_of` copies read it from a `&self` that cannot intern; the
  cube's plane type is therefore interned as a side effect of
  interning the cube, and the landing index is asked again after
  that recursion rather than remembered from the dedup scan.
  Everything above then follows without new machinery: a cube is an
  array of matrices at runtime, so `c[i]` is a plane that shares,
  `c[i, j, k]` desugars to the chain `c[i][j][k]`, `foreach`
  hands out planes, and a cube slice keeps the cube type with only
  the plane count opened.  A rank-3 literal recurses through
  `check_cubelit`, whose first plane settles whatever the type left
  open so a ragged cube is caught even under `T[,,]`.  The
  tuple-shaped `⍴` takes three extents and runs the same cutting
  loop twice — `cut_up` factored out of the rank-2 path — first
  into planes of `c×d` elements, then each plane into rows.
  `.shape` grows a third entry, `#m[0][0]`, reached the same way.
  Refused by name: rank 4 and beyond, cutting a cube with a range
  pair, matrix equality (the bootstrap threads it elementwise),
  printing a matrix, computed rows in literals, row stores on an
  open row length, open-extent arguments to fixed-extent
  parameters, `mut` matrix parameters.
- **range values**: `a…b` and `a…step…b` are expressions at the
  spec's precedence — tighter than comparison, looser than
  arithmetic — parsed in the binary-precedence loop, so `1 + 2 … 10
  - 3` is `3…7`.  The subscript and foreach parsers now take their
  ranges from the node rather than from the token stream, which
  left both surfaces unchanged.  A range value is a three-slot box
  `{lo, step, hi}`; the type is `131072 + elem` (no table — a range
  is three numbers and a direction, not a container).  A written-out
  header (`foreach i := 0…9`) still lowers as before; a range that
  arrives as a value unboxes and enters the same sign-agnostic loop,
  now factored as `lower_range_loop`/`range_alive` — the default
  step is a `cmov` on the bounds (±1, never zero), a written step is
  guarded by the interpreter's own "range step must not be zero"
  abort at the loop, as the interpreter raises it there and not at
  construction.  A `⍴` filler materializes the steps and reuses the
  array-cycling path, so `(2, 4) ⍴ (1…8)` runs across the row seam;
  untyped ends adopt the binding's element as the interpreter's do.
  Refused by name: `#`, subscripting, printing, and equality — the
  bootstrap compares ranges by identity (two equal spellings answer
  false), which is not a semantics worth reproducing.
- **lambdas**: `λx : T |cap| → R: expr` is a value — a box holding
  the code address of a synthesized function and the captures, read
  by value where the lambda is written, as the interpreter's are
  (mutating a captured binding afterward changes nothing).  Each λ
  lowers to its own function past the synthetics: parameters arrive
  in the argument registers, the box rides behind them as a hidden
  last argument, and the callee unpacks its own captures — so a
  named function's bare name also travels as a value in a one-slot
  box, ignoring the box register, and every call site is
  capture-agnostic.  Two new IR ops carry it: `IR_FADDR` (a
  RIP-relative `lea` through the same relocation list calls use)
  and `IR_CALLI` (`call r11`).  Signatures intern into an Ast table
  (band 132096+, parameters and answer; captures are the value's,
  not the type's).  The checker closes a scope floor over the body:
  it sees parameters, captures and functions, nothing else, and a
  `→ ∅` lambda parses (so an @expect may hold one) but refuses.
  `generate(f, r)` maps a range through any one-parameter function
  value into a fresh array, reusing the range materializer.
  Refused by name: parameters beyond five (the box must ride a
  register), container captures, and impure functions as values.
- **currying**: fewer arguments than parameters answers a partial —
  another closure box, holding a per-site shim's address, the bound
  values, and (when the target is itself a function value) the
  source box.  The shim receives the remaining arguments, unparks
  the bound ones in front, and calls on — directly for a named
  target, indirectly through the source box otherwise, which is
  what lets partials of partials compose without the shim knowing
  what it wraps.  An empty application answers the box unchanged
  (boxes are immutable), and `f()` on a named function is a
  zero-bound partial through the same path.  `(expr)(args)` applies
  any function-valued expression, so `f(1)(2)(3)` chains.  The
  chase fixed two latent bugs: `intern` on a program with no string
  literal walked `0…⁻1` downward into an empty array, and a
  synthesized lambda's prologue could overwrite the incoming box
  with a parameter whose checker slot landed on the box's register
  cell — everything incoming is parked in fresh temporaries first
  now.
- **type variables and @replaceable**: a name ending in `'` (the
  lexer lets the prime ride an identifier) is a type variable, alone
  in a signature.  The subset gives a generic function **one shape
  per program**: the first call that reaches it binds each variable
  to its argument's type, rewrites the signature concrete, and
  checks the body then and there — the caller's scopes parked and
  restored around the recursive check — so every later call meets an
  ordinary function, and a disagreeing call refuses where the
  interpreter would happily re-shape.  A `T'` return a parameter
  does not bind is settled by the body's first answer.  A generic no
  call ever reaches compiles to a stub.  `@replaceable` is capture
  discipline: inside a lambda such a function must be captured
  (`|mutable_fn|`), and the capture is the function's value-box read
  where the lambda is written, so the call inside the body goes
  through the box — one mechanism for captured locals, captured
  lambdas and captured functions.  Refused by name: replaceable or
  generic functions as bare values or curried, generic recursion,
  suffixes on type variables, and the empty capture list.
- **optional answers**: a function or lambda may answer `T?` — a
  bare value under an optional answer boxes itself at the return, ∅
  passes as the null, and `T!` rides the same box (what an error
  carries beyond absence is not core-2 yet).  The `?` postfix asks
  an optional and answers the function early with ∅ when nothing is
  there, unwrapping otherwise — inside a lambda it answers the
  lambda, because the lambda's body lowers in its own function.  A
  bare `÷` or `%` under `?`, or returned straight into an optional
  answer, treats the zero divisor as ∅ and boxes the quotient —
  the only places the subset lets division stand without `??`.
  Functions answering optionals now travel as values, so a captured
  `safe_div` composes with `?` inside a lambda.
- **multi-statement lambda bodies**: a λ body may be a layout block
  (statement by statement, as a function's), a brace block where
  layout cannot go — inside parentheses the lexer suppresses
  newlines, so `{ s; s; e }` separates with semicolons and the last
  statement is the value — or the single expression it always was.
  A block body checks and lowers exactly as a function body does,
  under the lambda's own return type (`lam_ret` overrides the
  enclosing function's for `return` and the trailing value), which
  is also why `return` inside a lambda answers the lambda: its body
  lowers in its own function.  A `:=` global may now be born of any
  function value — the box is built by the same init code that
  builds global dictionaries — and calls through a global's box mirror
  calls through a binding's, currying included.  Lambda shapes an
  @expect means to refuse (a parameter without a type, a missing
  return type, the empty capture list) parse and are refused by the
  checker, so the expectation machinery can hold them.
- **a stack the program reserves for itself**: the kernel's
  grow-on-demand stack is left where it is (argv's strings live on
  it), and `_start` — after copying argc and argv out — makes the
  stack it will actually stand on: one `mmap` of `guard + stack`
  bytes, `PROT_NONE` throughout so the whole region is reserved
  address space, then one `mprotect` opening the upper `stack`
  bytes for reading and writing.  What stays unreadable below is
  the guard, so an overflow faults on it instead of walking into
  whatever the kernel put beneath; `rsp` moves to the head of the
  region and the program runs there.  `--stack-size=N` and
  `--guard-size=N` (bytes, or `K`/`M`/`G` of them, rounded up to
  whole pages, one page to a gibibyte) override the defaults of 8
  MiB and 64 KiB.  Because the compiler knows every frame it lays
  down, it refuses a program whose deepest frame exceeds the guard
  — that frame's single `sub rsp` could step clean over the guard
  and land past it — and one whose deepest frame exceeds the whole
  stack, naming the size to raise.  The image carries `PT_GNU_STACK`
  (read and write, pointedly not execute; its `p_memsz` records the
  requested size), without which the kernel falls back to an
  executable stack.
- **the process environment**: `std.env.names()`, `std.env.get(name)`
  and `std.env.has(name)`, all three impure as reading the arguments
  is.  `_start` keeps `envp` beside argc and argv — it is argv plus
  the NULL that ends it — before the stack moves, so the block and
  the bytes it points at outlive the move.  Two runtime routines
  carry it: one walks the block making a `str[]` of the names, each
  the part before the first `=` (or the whole entry, for one that
  has none, as the interpreter reads them); the other walks it
  looking for a name, answering the box holding the value or the
  null, first match winning as `getenv` has it.  `has` needs no
  routine of its own — it is that answer against zero — and
  `std.env.count()` is refused by name, since its `count` unit is
  not one core-2 carries.  `examples/printenv.ngpl` is the utility
  those three make, and its output matches the interpreter's and
  `/usr/bin/printenv`'s byte for byte.
- **the process itself**: `std.process.pagesize`, `.uid`, `.euid`,
  `.gid`, `.egid`, `.secure` and `.exec_filename` — members, not
  calls, because the ELF auxiliary vector they come from is written
  once at `execve` and never changes, which also makes reading them
  pure.  `_start` walks the environment to its NULL and keeps the
  word past it: that is where the kernel left the vector.  One
  runtime routine scans it for a key, so six of the seven members
  are one call and an immediate, `secure` being that answer against
  zero; the seventh takes `AT_EXECFN`'s address and measures the
  bytes into a string.  The identities are `u32` and the page size
  carries `¤byte`, as the spec has them.
- **three kinds of data, and a program that seals its own**: a
  global that is never written rides in the read-only segment with
  the strings; one the initializer builds — a dictionary, a function
  value — is written before `@start` and never after, and sits at
  the head of the writable segment together with what the kernel
  handed over (argc, argv, envp, the auxiliary vector), padded to a
  page; a `mut` global and the allocator's own state follow it and
  stay writable.  `PT_GNU_RELRO` records that head, and since
  nothing loads a static program but itself, the program does what
  a dynamic loader would: after the initializer has run and before
  anything else does, it walks its own program headers — `AT_PHDR`,
  `AT_PHNUM` and `AT_PHENT` from the auxiliary vector — and
  `mprotect`s every `PT_GNU_RELRO` stretch read-only, rounding the
  ends inward to whole pages as a loader rounds them.  For the
  headers to be readable at all the image now maps them, in a
  read-only `PT_LOAD` of its first page, which is also what makes
  the kernel's `AT_PHDR` point at something.  Where a global lives
  is a compile-time map consulted at every load and store, so the
  three kinds cost nothing to tell apart at run time.
- **a symbol table**: the image now carries `.symtab`, `.strtab` and
  `.shstrtab` with section headers for `.text`, `.rodata` and
  `.data`, so `nm`, `objdump` and a profiler can say what code
  belongs to what.  Nothing has to be mangled into an older
  convention -- the language starts from scratch -- so a name is the
  normalized spelling of the signature itself: `many(i32, u8, bool,
  str, char) -> i64`.  Parameter names are a reader's business and
  are left out; the types that *are* the signature are kept, spelled
  the way the language spells them (`&i64[]`, `i32[,]`,
  `std.dict(str, i64)`, `str?`, `i64` with its unit, and the empty
  set for nothing).  A named type carries a hash of what it is
  defined to be -- `Point#fdbb58f9c5cba14c` -- taken as FNV-1a over
  a normalized definition: the name, then each field's name and type
  in order, with a field's own struct type spelled the same way
  recursively.  So renaming a field, changing one's type, or
  changing a struct a field reaches through all change the hash,
  while a definition that refers to itself contributes its bare name
  the second time round and the spelling terminates.  Every function
  is a symbol, local unless `@export` says otherwise; the entry
  point, the runtime's routines and the compiler's own synthesized
  functions are named as locals too, so no part of the text is
  anonymous.  A symbol table names its locals before its globals and
  says where the globals begin, which is what the two-pass build is
  for.
- **what a measure may meet**: the rule is the operator's, not one
  rule for all arithmetic.  A sum, a difference, `⌈`, `⌊`, the
  saturating pair and every comparison want their sides measured
  alike -- a plain number is not a length -- while an untyped number
  takes whatever measure it meets.  A product scales: one side
  measured and one plain keeps the measure, and two measured sides
  make a measure of their own (`ptrdiff×ptrdiff`), which core-2
  cannot write down and so refuses by name.  A quotient divides the
  measures out, so two alike cancel to a bare count; a remainder
  keeps what was divided.  A conditional is lax, as the bootstrap is
  lax: it hands one side on rather than operating on both.  What is
  wanted of a sum is wanted of each side, but what is wanted of a
  product is not -- pushing a measure into a product's operands
  would have the untyped `1` in `(pos + 1) × 1¤ptrdiff` come out
  measured, and then be added to a plain `pos`.
- **only the runtime a program reaches**: the routines are emitted
  last, once the program's own code has been laid down and the calls
  it made are known.  Those seed a reachable set, closed over a
  table of which routine calls which -- extracted from the emitter
  itself rather than written by hand -- and everything outside the
  set is passed over.  Passing over is one switch: while it is on,
  the emitter's byte sink and every fixup it records go into the
  ground, so a routine is skipped without any of the emission code
  knowing there is such a thing as skipping.  A routine that is
  passed over is left without a place, so a call that somehow still
  reaches for it has nowhere to land, and resolving the calls says
  so and stops -- which is what keeps the table honest: removing one
  edge from it by hand halts the compiler rather than producing a
  binary that jumps into the wrong routine.  A program that does
  nothing carries 11 of the 44; the compiler itself carries 33.
- **an optional is a value like any other**: what `pop` and `get`
  answer is the optional itself, not a value that has to be given a
  default on the spot.  `?? d` is one thing to do with it rather
  than the only thing: it binds, it matches, it compares with `∅`,
  it is handed back.  Under `??` the value still arrives bare and
  nothing is allocated -- the boxing happens only where the optional
  is what the program asked for -- which is the same shape `next()`
  already had.  A tuple may be optional too.  Its code sits far
  above the optionals' band, so `base + 2048` would land inside the
  tuples' own; an optional tuple therefore gets a band of its own
  past the type variables, and the three words that make, test and
  open an optional are the only ones that had to learn about it.
- **UTF-8 through a shift-based DFA**: `.chars()` decodes with
  Höhrmann's automaton in the shift form the design researched --
  nine states and twelve byte classes, a state kept already
  multiplied by its field's width so the step is
  `state = T[class] >> state & 63` with no multiply, and the code
  point grown six bits a byte.  Whether a byte begins a character
  or continues one is three conditional moves, so the ladder of
  compares and its inner continuation loop are gone and the only
  branch left in the body is the one that says a character is
  finished.  The tables (256 class bytes, twelve transition words)
  ride in rodata beside the strings, through the same kind of fixup
  a global there uses.  The automaton also *knows* malformed UTF-8,
  which the ladder could only mis-decode; nothing in core-2 can
  build an invalid string yet, so that is machinery in hand rather
  than a check being made.  Measured against the ladder it
  replaced, on both repeating text and text whose character widths
  are chosen unpredictably: no difference.  `.chars()` allocates
  eight bytes for every input byte, and that is what the time goes
  on -- the decode was never the cost.
- **walking a string reads it where it lies**: `foreach ch := s` no
  longer lays the characters out in an array first.  It keeps a byte
  position and asks the runtime for the character there and where the
  next one begins, which is the same shift-DFA run until it says a
  character is whole.  The position moves before the body, so
  `continue` leaves the walk where the next character starts.  What
  this saves is not instructions but memory: the array cost eight
  bytes for every byte of the string, and the arena does not take
  them back, so a walk repeated was a walk that grew.  Walking a
  50 KB string 400 times went from 185 MB of peak resident memory to
  52 MB, and 2000 walks over a 5 KB string now peak at 3.8 MB --
  which is the string itself.  A program that only walks strings no
  longer carries the routine that lays them out at all; the dead
  runtime is dropped as any other unreached routine is.
- **enums and type names**: `enum Name [: width]:` with one
  enumerator to a line names what a value may be.  What a value
  holds is the number it was given -- counted from zero, or counted
  on from whatever an enumerator says it stands for (`ok = 0`,
  `warning = 10`) -- so `Name.enumerator` folds to a constant where
  it is written and costs nothing at run time.  An enum is asked
  which it is, never put in an order, and only against its own kind;
  it rides in arrays, parameters, returns and optionals as any
  scalar does.  The band is carved out of the top of the structs'
  (1792..2048, leaving 768 structs), which keeps every named type
  below 2048 and so keeps an optional of one at `base + 2048` with
  nothing else to teach.  `type Name = T` gives a name to a type and
  nothing more: it resolves where any type name resolves, so it
  stands for its type everywhere including inside another alias.
  Refused by name: writing an enum's value out (the interpreter
  prints `Color.green`, which wants the names in the image), and
  `@flag` enums.
- **measures with names, and a file's own**: a unit is an index into
  the file's list of them rather than one of two hardcoded kinds.
  The list starts with the ones the language ships -- `meter`,
  `second`, `kilogram`, `count`, `distance`, the SI multiples and the
  byte multiples, alongside `ptrdiff` and `byte` -- and `unit name`
  adds one of the file's own, written `¤"name"` where a shipped one
  is written `¤name`.  A measured value prints with that measure's
  own mark (`5 m`, `9 widgets`), which is the interpreter's mark for
  it.  The rules are the ones already in place per operator: alike
  meets alike, a plain number scales, two alike cancel to a bare
  count.  A measure written by a binding's name measures what an
  array holds, so `let d ¤meter : i64[]` is an array of lengths.
  Room for this came from the integer type's own code rather than a
  new band: core-2 holds four widths, so two bits say which, and the
  five bits that spelling a width out used to take now hold the
  measure -- 125 of them, in the same 16..1023 the integers always
  had, so every other band stayed exactly where it was.  Refused by
  name: a measure derived from others (`unit mph = … × meter ÷
  second`), and conversion between related measures -- core-2 keeps
  measures apart rather than converting between them, so `km + m` is
  refused where the bootstrap converts.
- **branch hints**: `@likely` and `@unlikely` stand before an `if`
  and say which way the condition is expected to go.  They belong to
  that statement and to nothing else, and they never change what is
  computed -- what they change is where the code goes.  Without a
  hint the then-block falls through, which is the common case a
  reader assumes; `@unlikely` says otherwise, and where there is an
  else the two arms swap for nothing: the same instructions, with the
  cold block out of the straight line.  With no else there is nothing
  to swap it against, and the layout stands (moving it would want a
  cold section the emitter does not have).  `@hot` and `@cold` on a
  function or method are accepted and noted, as the interpreter notes
  them; acting on them wants control over the order functions are
  emitted in, which is its own piece of work.
- **the test harness**: `@test` functions compile into the binary and
  run before `@start` — silently when they pass, the first failing
  assertion stopping the run.  The binary honors the interpreter's
  own options: `--skip-tests` bypasses them, `--test` reports each
  test and the summary on the error stream in the interpreter's
  exact format and exits without running `@start`; a synthesized
  argument filter keeps both flags out of `std.args.all()`, as the
  interpreter keeps its options out of a program's arguments.  An
  `@expect` definition — a function or global expected to draw
  diagnostics — is parsed and left uncompiled (the interpreter is
  where the expectation itself is verified), and the same mark may
  stand over a single statement inside a body.  A statement expected
  to draw an *error* is left alone the same way: it does not check,
  so there is nothing to compile, and what follows it is compiled and
  run as usual.  One marked only for a *warning* is an ordinary
  statement here — core-2 has no warnings to draw — so it checks,
  runs, and anything it really gets wrong is still reported rather
  than swallowed.  That distinction matters: catching every
  diagnostic a marked statement draws would turn a refusal ngplc
  makes and the bootstrap does not into silently missing code, which
  is how the first attempt at this went wrong.  A reference to one is
  answered with "expects errors under @expect and was left
  uncompiled", and `--test` still reports it in the suite's shape.
  The driver and filter are ordinary synthesized IR functions, so
  they cost two small functions in every image and nothing at run
  time when no flag is given and no test exists.

## The Files

The compiler is thirty-seven source files.  There is no list of them:
each says at its head what it is written against, with
`@import("./other.ngpl")`, and the compiler is handed `src/main.ngpl`
and follows those, putting each file after everything it names.
Twenty-four of them were cut from one 20,836-line file by contiguous
slices -- concatenating them in that order reproduced it byte for byte,
and the binary they compiled to was byte-identical on all six targets,
which is how the split was checked.  The rest were written afterwards,
`comptime.ngpl` first.

    tokens imports types diag lex ast parse dumpast check abi comptime
    ir lower emit sha256 symbols sbom incr elf
    arch_x86_64 rt_x86_64 arch_a64 arch_rv64 arch_i386 arch_arm
    arch_rv32 dispatch tdriver rt_hash rt_sha256 rt_bigint rt_signal
    rt_backtrace rt_portable codegen_t codegen main

That is the order the imports put them in, not an order anyone wrote
down.  Build it with `ngplc src/main.ngpl`, or with
`ngplc --build src/main.ngpl`; the recipe in `main.ngpl` is a `@build`
function, which generates no code and cannot be called, and it adds one
executable rooted in that one file.

**The order is part of the program**, and the program says it.  A
struct, a function, a global and an `enum` may be declared below
whatever names them — the parser sweeps for struct names before parsing
and the checker resolves the rest afterwards — but a `unit` is
registered as it is read, so `elf.ngpl` has to precede everything that
writes `¤"shndx"`.  Each file names what it is written against at its
head and the compiler follows those, so alphabetical order never comes
into it and no list outside the sources can drift from them.

One seam the list does not hide: `impl Emit` is opened in both
`emit.ngpl`, which declares it, and `arch_a64.ngpl`, which adds the two
methods aarch64 writes words through.  The language allows a second
`impl` block and this was already true inside the one file.

## Modules

A `module` line is a section marker: what follows belongs to it until
the next one says otherwise.  Three things make it work in a compiler
that reads a file once.

The **modules are pre-scanned**, in the same sweep that gathers struct
names, and for a sharper reason: `a.b.f()` reads as a field of `a`
until it is known that `a.b` is a module, and the module may be
declared further down the file.  The sweep replays the sectioning,
since what a bare name means depends on the module in hand when it is
read.

A **qualified call is settled in the parser**: the longest run of
identifiers that names a module is the module, what follows is the name
asked of it, and the module is written down beside the call (`nb`, one
past its index) so the checker looks it up there rather than walking
out through the enclosing modules.

**Two lookups, one tail.**  A bare name walks out through the modules
it is written inside; a qualified one asks the module it named and is
refused if that module did not export it.  Everything after -- purity,
arity, each argument against its parameter -- is the same either way,
so both go through `check_resolved`.

The object-file symbol is the whole name and the signature:
`shapes.solid.volume(i64, i64, i64) → i64`.

## Pipeline and Data Flow

Unchanged in shape from attempt 1 — flat parallel arrays and ids
throughout, every post-parse pass per-function over immutable inputs,
serial today but shaped for the parallel compiler:

    bytes ──lex──▶ Toks ──parse──▶ Ast ──check──▶ types/slots
                                     ├──lower──▶ IrFn (per function)
                                     └──emit───▶ code ──layout──▶ ELF

Types are one integer each: `16 + sgn + 2·bits + 256·unit` for the
integer family, `4096 + elem` for arrays, `65536·refkind` added on
parameters.  The checker threads a `want` type downward so untyped
literals settle where the spec settles them, folds literal-only
subtrees exactly, and stamps every node with a type and every binding
and use with a frame slot.  The IR carries a width (`bits + 256·sgn`)
on every operation, which is all the backend needs to pick
instructions, condition codes, and checks.

## The Control-Flow Policy, Applied

CLAUDE.md's policy: decisions are data; an `if` that needs a jump is
the exception.  The research behind the choices here — cmov
profitability, if-conversion legality, switch lowering thresholds,
GPU divergence — is summarized with sources at the end.

**In the compiler's own source.**  The lexer classifies every byte
through a 256-entry class table; single-byte tokens are the table
entry itself.  Multi-byte glyphs resolve by one hash probe over their
packed UTF-8 bytes, keywords by one probe of the keyword hash — no
comparison ladders.  Columns are characters, counted by the
lead-byte test `(b & 0xC0) ≠ 0x80`.

**In the generated code.**

- Comparisons materialize with `setcc`; truth values are 0/1 and
  combine with `and`/`or`/`xor`.
- `⌈` and `⌊` are `cmp` + `cmovcc`, signedness-aware, always — their
  operands are evaluated regardless, so nothing is speculated.
- `if c: a else: b` becomes a `cmov` select when both branches are one
  expression apiece and both are **safe to speculate**: no effects and
  no faults.  The legality rule follows
  what real compilers use: variables, constants, `@wrap` arithmetic,
  bitwise ops, comparisons and selects of such pass; checked
  arithmetic (may abort), array indexing (bounds abort), and calls do
  not.  Otherwise the conditional stays branched.
- `and`/`or` with a speculatable right side are evaluated eagerly —
  three straight-line instructions instead of a branch; the
  short-circuit form remains only where the right side could be
  observed (effects or faults).
- A dense ladder whose every arm **returns a constant** (default
  included) is not control flow at all: it folds to a **value table**
  — index clamp by `cmov`, one load from a table of data in rodata,
  one `cmov` against the default — zero branches, GCC's
  switch-conversion made policy.  Verified in the binary: the folded
  function carries no indirect jump and two cmovs.
- A dense if/elif ladder testing one variable against integer
  constants (whose arms are real code) lowers to a **jump table**: bounds check (`sub`; unsigned
  `cmp`+`jae`, one never-taken branch to the default), then one
  indirect `jmp [table + idx*8]` through a table of code addresses in
  rodata.  Profitability follows the window real compilers use: at
  least 4 cases and span ≤ 3× the case count (LLVM asks ≥4 and ≥10%
  density; GCC's -O2 ratio is 8); sparse ladders stay ladders, which
  the research says is right — an indirect jump predicted worse than a
  short predictable ladder is not a win.
- Aborts (overflow, shift range, bounds, contract violations) stay
  **cold branches to out-of-line stubs**: `jo/jc/ja` to a routine that
  writes the message and raises SIGABRT.  This is deliberate policy,
  not a violation of it: a never-taken, perfectly-predicted branch
  costs ~0 on the hot path and is exactly what production checkers
  (UBSan's `jo`-to-trap) emit.  The branch-free alternative — a
  sticky error flag ORed per operation, tested at statement ends
  (IEEE-754 flags, CERT's As-if-Infinitely-Ranged model) — is the
  planned lowering for the future vectorized/GPU profile, where it is
  the only sound branch-free form; its deferral window must close
  before a poisoned value feeds an address or a branch.

- The emitter keeps a one-register memo: it knows which slot's value
  `rax` holds, skips the reload when the next operand is that slot,
  and forgets at labels, calls, and every join two paths reach — the
  cheapest of register allocations, worth ~3% of code straight away;
  the true linear-scan allocator remains on the plan.

- **A convention of our own, between functions nobody outside can
  call.**  `src/abi.ngpl` reads the AST once and marks every function
  the program does not export whose address is never taken — neither as
  a bare name (`NK_FNVAL`) nor into a lambda's capture box, the two
  ways one gets out, both ending in an indirect call that agreed with
  the architecture rather than with us.  Of the compiler's own 1091
  functions, 1090 qualify; only `main` does not, being where the loader
  enters.  Every decision is written to `--log=json`.

  What that buys is spent on i386, arm and riscv32, which passed *every*
  argument on the stack: an `i64` arrives as a pair on all three, and
  the simple course when they were written was to put every pair in
  memory — four instructions at the call site and four in the prologue,
  per argument, per call.  Their abstract registers are cells in the
  frame (`i3_cello`, `a32_cello`, `r32_cello`), so a body moves memory
  through one pair and touches nothing else, which leaves the rest free
  end to end.  A private function therefore takes its first arguments in
  registers — three on i386, two on arm, four on riscv32 — and preserves
  none of them, there being nothing a caller here keeps across a call to
  lose.  Measured on the compiler compiling itself, `.text`:

  | target | before | after | |
  |---|---|---|---|
  | i386 | 6707053 | 6445947 | −3.89% |
  | arm | 5124104 | 4931016 | −3.77% |
  | riscv32 | 5670956 | 5380268 | −5.13% |

  Each figure understates the code-generation gain, since the compiler's
  own source grew by the change being measured.  The three 64-bit
  targets are untouched: they already take six or eight arguments in
  registers, and the 61 of 1088 functions with more parameters than that
  are nearly all one-shot emitters that run once.

  Two orderings hold it together and are the same fact twice: in the
  prologue the register arguments reach their slots before the stack
  ones are read, and at the call site the stack arguments are put down
  before the register ones are loaded — because on each of these targets
  a stack argument travels through the very pair argument 0 lives in.
  An assertion at `IR_FADDR` refuses any address that reaches a function
  holding a private convention, so an escape route the analysis has not
  been taught shows itself at the first compile rather than in a
  cross-target diff.

- **Inlining, written and measured and not yet worth it** (branch
  `todo/inlining`).  Two policies, both working: a function called from
  exactly one place read at that place whatever its size, and one called
  from several read only where the body is shorter than the call.
  Measured on the compiler compiling itself:

  | policy | instructions | text |
  |---|---|---|
  | bodies ≤ 24 nodes, wherever called | +1.53% | +5.6% |
  | called once, whole body | +12.8% | +48.4% |

  Half that text is an unfinished job — the body that was read is still
  emitted where it stood, and stubbing out what nothing calls any more
  would take it back.  The instructions are not: dead code executes
  nothing, so 12.8% is work really done.

  The cause is the shape above.  A call passes its arguments as
  registers set up and spilled again by the prologue; a body read in
  place binds them as a copy from one slot to another, which where every
  operand already goes to memory and back is no cheaper.  What is
  removed is the call and the return; what is added is a move for the
  answer and a larger frame.  Values that stay in registers across the
  boundary the inlining removed are the whole of the win, and until the
  allocator exists none of them do.  Off, it still cost 1.84%, the remap
  being ten more calls on every slot the lowering resolves — so it lives
  on a branch rather than here, and the numbers above say what to
  measure it against when the allocator lands.

- **What the allocator has to be, established by measurement.**  Three
  shapes were costed before writing one, and two of them are ruled out.

  *A wider memo* — the `rax` trick extended to `rbx` and `r12`–`r15`,
  which the pioneer never touches — serves a load from a register
  instead of the frame.  But `mov rax, r12` replaces `mov rax, [rbp-N]`
  one instruction for one: it buys bytes and cycles and **not a single
  instruction**, which is the measure that has decided everything else
  here.  A memo cannot help; only removing memory operations can.

  *Making the 32-bit abstract registers real* looks like the biggest
  prize, since `RG_A/B/C` are cells in the frame on i386, arm and
  riscv32 — every operand is a load, a store and a load back, roughly
  three times the traffic of aarch64 and riscv64, where they are
  registers already.  It cannot be done by substitution: `i3g_mul3`
  needs `eax:edx`, `ecx:ebx` *and* `esi:edi` at once for one 64-bit
  multiply, so all three pairs are scratch for a single operation.  The
  cells are load-bearing, and replacing them needs an allocator that can
  spill, not a renaming.

  *Removing the stores* is what is left, and it is where the
  instructions are.  A temporary costs a store to its slot and then a
  load the memo already skips, so the store is the waste; for a value
  whose only reader is the next operation it is pure loss.  It needs
  last-use information, which can be had conservatively without a
  per-opcode operand table by treating every field of every operation as
  though it named a vreg — over-approximating only ever costs a
  missed store, never a wrong answer.  The one real hazard is
  re-entry: a backward jump can reach a read that lies *before* the
  store, so a store may only be dropped when no jump after it targets a
  label at or before it.

**What stays a branch, on purpose.**  Loop back-edges and loop-bound
checks (predictable, and the loop-carried-dependence research is
unambiguous that cmov loses there); the short-circuit forms with
effectful right sides (semantics); the cold abort paths (above).

## Runtime

A few routines over raw syscalls, emitted before user code:

- `rt_alloc`: bump pointer over `mmap` regions (≥1 MiB at a time),
  state in the RW data segment; no free.  Arrays are `{data, len,
  cap}` descriptors, growth by doubling with copy; strings are
  immutable `{data, len}` descriptors, literals as static descriptors
  in rodata.
- string concat/equality/character-count (the count is the lead-byte
  test materialized with `setcc` — a branch-free body), signed and
  unsigned decimal printing, `write`, and the abort path
  (`write(2, …)`, then `kill(getpid(), SIGABRT)`).
- the hash table behind `std.hash`: one allocation holding a
  40-byte descriptor `{ctrl, kv, count, cap, keystr}`, one ctrl byte
  per slot, 16-byte key/value pairs, capacity a power of two,
  growth by doubling at 7/8 load with rehash.  The probe is the
  Swiss table's: a held slot's ctrl byte is its hash's low seven
  bits with the high bit set, so it is never zero and an empty slot
  stays the zero that fresh mmap already is — no clearing on
  creation, and the two questions a probe asks are two SSE2
  compares over sixteen slots at once.  `pcmpeqb` against the tag
  broadcast to all lanes and `pmovmskb` give a bitmask of the
  candidates, walked with `bsf` and cleared with `x & (x-1)`; a
  second compare against zero says whether the group has room, and
  if it has, the key is not in the table at all, since a run of
  probes never steps over an empty slot.  Groups are aligned to
  sixteen and the capacity is a power of two no smaller, so a group
  never straddles the end of the ctrl array and needs no mirrored
  bytes after it.  Measured against the linear probe it replaced:
  1.8× on 200k keys with hits and misses mixed.
  Integer keys hash through the murmur3 finalizer, `str` keys through
  FNV-1a with equality by `rt_streq`.  `rt_hfind` is the one probe
  loop; get/put/membership/grow ride on it (it leaves the descriptor
  and key in preserved registers for them).  A get boxes the value
  into a fresh optional.  The full Swiss-table shape — tags probed 16
  at a time with `pcmpeqb`+`pmovmskb` — remains the planned upgrade;
  the descriptor already carries what it needs.
- the character quartet: `rt_stridx` (skip to the i-th lead byte —
  each character's length from three materialized `setae` adds, no
  branch — then decode), `rt_chars` (decode a whole string into a
  fresh array, capacity bounded by the byte length), `rt_charstr`
  (encode one scalar as 1–4 UTF-8 bytes in a fresh string), and the
  `rt_badchar` abort stub behind `.chr()`'s two cold checks.

The ELF carries three PT_LOADs: text R+X, rodata R (string bytes,
string descriptors, jump tables), data R+W (globals' initial values
and the allocator state).  No libc, no relocations at run time —
every address is patched at layout.

### The File Is Written, Not Assembled

The file's own structures — `Elf64_Ehdr`, `Elf64_Phdr`, `Elf64_Shdr`,
`Elf64_Sym` — are declared in the compiler's source as `@repr(C)`
structs with the field names `<elf.h>` uses, and are written out as
themselves.  Nothing pushes a header into a byte array a half-word at
a time, and there is no single image: `build_elf` answers an `Elf`
holding the fourteen pieces the file is made of, `std.iov` turns each
into a `std.iovec`, and the writer hands the array of them to `writev`
in one call.  A table — the program headers, the symbols, the section
headers — is an array of its entry type and one run, so the kernel
does the joining that a buffer used to.

A run is a value rather than an argument position, which is what lets
the writer build its list the way it builds anything else: push in a
loop, count what it has, hand the array over.  `std.iov` settles the
bytes where it is called — a byte array is already its own bytes, a
struct is packed by a straight-line sequence the lowering emits from
the layout, a table is that same sequence inside a loop — so a run
carries a base and a length and nothing that still has to happen.

Only what ELF gives no structure to stays a run of bytes: the text,
the read-only and writable images, the two string tables, and the
gaps between segments.  A struct's own padding is written as zeros by
the packer, so the same source still produces the same file.

The fields carry no `@wrap`.  A written-out number or an `i64` meets a
`u16` or a `u32` field the way it meets any narrower type — accepted
with a fit check the lowering emits — so the annotation was noise
carried over from the byte-pushing it replaced, where `@wrap(v) & 255`
genuinely needed it.  Dropping it also restores the checking it was
suppressing: `sym_info(bind, kind)`'s packing and `text_vaddr + sy.value` are
now watched for overflow like any other arithmetic, and a header field
that cannot hold what it is given stops the compiler instead of
quietly keeping the low bits.

**Every field says what it holds.**  A field whose value ELF draws
from a fixed set is an enum with a fixed representation — `Et`, `Em`,
`Ev`, `Pt`, `Sht` and the `@flag` enums `Pf` and `Shf` for the
headers, `Stb`, `Stt` and `Stv` for a symbol — and a field that counts
something carries the measure it counts in: `¤byte`, or one of
`shndx`, `symndx`, `phndx` for the three kinds of index the file has.
What is left is left deliberately.  `st_info` stays a byte because it
is not one enumeration but two packed into one, so the two are enums
and `sym_info(bind, kind)` is the single place the packing is written.
`e_ident` stays a sixteen-byte array because that is what `<elf.h>`
declares, but `elf_ident(class, order, abi)` builds it from named
values rather than from a row of numbers.  `e_flags` stays a plain
word because its meaning belongs to the machine rather than to ELF —
what a bit says for arm it says for nothing else, and its top byte is
not a flag at all but an ABI version — so the one architecture with
something to put there names its pieces (`EF_ARM_EABI_VER5`,
`EF_ARM_ABI_FLOAT_SOFT`) and composes them.

The typing is invisible in the output, which is the test it has to
pass: an enum folds where it is written, so the same source produces
the same file, and every step of this was gated on the six targets'
binaries staying byte-identical.  It is not invisible in the source,
where the ordering rule bites — an enum must be declared before its
name is used as a type, so the symbol enums sit above the structures
that name them.  The bootstrap caught that: the interpreter reads an
enum declared below its use, and ngplc refuses it, so a file that
loads happily still failed to compile itself.

Two further things follow from writing structures instead of bytes.  Every
offset is now settled before anything is written — `e_shoff` used to
be patched back into the header afterwards, and there is no patching
left.  And the fields are typed, which found two bugs the byte-pushing
had hidden: `_start`'s size was the distance to the first *runtime*
routine rather than to the next function (960 KB in a 1 MB binary),
and the symbol after the last runtime routine had a negative size that
`push64`'s masking quietly turned into a large positive one.  Both
were one mistake — the symbol list was not in address order.  The
functions come before the runtime in the text, and a runtime routine's
id is its place in the list rather than its place in the code, so the
surviving routines are sorted by address before their sizes are taken.

## Six Targets, One Driver

The backend is a pioneer and a framework.  x86-64 keeps the original
hand-tuned emitter; every other architecture arrives through a shared
retargetable path, so a new one is a spelling exercise rather than a
port.

**A Target descriptor** carries what varies: the ELF machine number
and class, the pointer width, the Linux syscall numbers, e_flags, and
the per-arch quirks (O_DIRECTORY, st_size's offset, whether the arch
even has fstat).  `--target=A` selects a row, defaulting to the host.

**std.filetype is an enum too.**  It was a bespoke type code (TY_FTYPE)
that behaved like an enum without being one; it is now the first row
of the enum table every file holds, so `.ord()`, the comparison rule
and `@typeof` all reach it through the ordinary path and the special
code is gone.  A builtin enum is reached through `std`, never by its
bare name, which is what the two written-name lookups skip past.

**The structures speak in enumerations.**  e_type, e_machine and
e_version, p_type and sh_type carry enums with the format's fixed
widths (`Et : u16`, `Em : u16`, `Ev : u32`, `Pt : u32`, `Sht : u32`),
and the two genuine bit fields carry @flag enums whose members are
the format's bits in <elf.h>'s order: `Pf : u32` (x, w, r) and
`Shf : u64` (write, alloc, execinstr), combined with `|` at the six
program-header and seven section-header rows.  The one seam: ELF32's
sh_flags is a Word where Shf's fixed representation is u64, and a
fixed-width enum cannot be two widths, so the 32-bit copy takes the
bits out by number with `.ord()` — the same narrowing libelf performs
between GElf_Shdr and Elf32_Shdr.  Target.machine is an `Em`, so a
target row names its machine rather than remembering 183.

**The structures are measured.**  Offsets, sizes and addresses in the
ELF structures carry ¤byte; section indices ¤"shndx", symbol indices
¤"symndx", program-header counts ¤"phndx" — units the compiler's own
source defines.  Every variable in `plan_elf` that computes a field
carries the field's unit, so an index cannot wander into a byte count
without `@dropunit` saying so.  The units are typing only: the emitted
files are byte-identical with and without them.

**One ELF plan, two spellings, in the gelf manner.**  The 64-bit
structures are wide enough to hold everything a 32-bit file says, so
`plan_elf` builds the final Elf64 forms outright — as libelf's
`gelf_*` functions have it.  A 64-bit file hands them to the writer
as they are, so the common path copies nothing; a 32-bit file narrows
copies on the way out, including the two field reorderings the format
asks for.  The values are the file's own either way: the offsets are
computed with the class's entry sizes, so a 32-bit plan holds 32-bit
truths in 64-bit fields.

**An abstract machine** of four 64-bit registers and slot-resident IR
values, with ~40 operations.  The driver `t_emit_fn` composes every IR
op from those once; the x86-64 emitter stays as the measure.

**Only what a program reaches is emitted.**  Both drivers seed the set
from the calls the program's own code made and close it: x86-64 over
`rt_edges()`, a list kept by hand because its routines are machine code
and cannot be asked; the retargetable driver by emitting in waves until
a wave adds nothing, which catches the calls the driver itself puts in
for an overflow or a bounds check and that no IR mentions.  A routine
nobody reached is in no binary and is no symbol either, and the rest go
into the symbol table by address, since a routine's id is its place in
the list rather than in the code.  It is worth a good deal: a hello
world for i386 went from 141 KB to 41 KB when the retargetable driver
learned this.

**The runtime is written once as IR** (`rt_portable.ngpl`) and compiled by the
same driver for whichever target is asked, so 47 routines exist in a
single portable spelling.  This is why the sources hold an
`rt_x86_64.ngpl` and no `rt_aarch64.ngpl`: the pioneer's runtime is
machine code written out for one target, and the other five have one
runtime between them, which is named for how it is written rather than
for any of them.

**The hash routines are written once for all six.**  `rt_hash.ngpl`
and `rt_sha256.ngpl` are arithmetic and nothing else — no kernel, no
calling convention of their own — so there is nothing a hand-written
version would know that the IR does not, and the pioneer compiles the
same builders through `emit_fn` that the other five compile through
`t_emit_fn`.  That is what `emit_fn` learning `IR_LDN`, `IR_STN` and
`IR_KADDR` bought: the pioneer can now compile anything the portable
builders write.  The arithmetic is 32 bits wide and says so — `add32`
and `shl32` leave the driver's `t_canon` to do the narrowing that the
same algorithm written in the language spells as `& 0xFFFFFFFF` at
every step.  It is what makes a bill of materials free: 482 s for
stage 1 with one and 485 s without.

The split between the two files is the seam an algorithm is added at.
`rt_hash.ngpl` knows only that bytes go into a block and the block is
absorbed when it fills, which is every sponge and every
Merkle-Damgård hash; `rt_sha256.ngpl` answers the three questions the
handle asks an algorithm — how it starts, how it compresses a block,
and how it finishes.  A second algorithm writes three routines and
touches three lines.  What 64-bit hardware does in one instruction the
32-bit targets get as shared software: 64-bit divide/remainder
(shift-and-subtract) and multiply-overflow (four half-products), as
RT_*64 helpers the IR builders never recurse into.

**The instruction layers**, each verified against llvm-mc before use:
aarch64 (~60 fixed-width words), riscv64 (RV64IM, flags materialized
since RISC-V has none), i386 and arm (8-byte model carried in memory
cell-pairs, since neither has 64-bit registers), and riscv32 (the
RV64 encoders reused with pair arithmetic).

Every target runs all 61 conformance programs and all 16 shared
--test files byte-identical with the interpreter, under qemu for the
cross targets and the native loader for i386.

### What the ports taught

Almost every bug was a byte, and almost every one was caught by a
tool rather than by reasoning:

- **llvm-mc is the second reader.**  Verifying encodings before use
  caught eight hand-converted aarch64 constants; a later cross-check
  caught that a sweep of corrections had chained two replacements and
  turned every 64-bit load into a store.
- **The compiler's own checked arithmetic caught its own bugs.**
  movn's ~v overflowed on INT_MIN; the RISC-V large-constant seam
  carried on INT_MAX's low half — both aborted the compiler on itself
  until the @wrap was written where the wrap was meant.
- **A syscall answer is not wholly signed.**  Sign-extending a 32-bit
  return turns a high mmap address into an error; only the errno band
  (−4096..−1) is negative.
- **The quirks live in the row, not the code.**  O_DIRECTORY is
  0x10000 on x86 and RISC-V but 0x4000 on ARM; st_size sits at a
  different offset per 32-bit ABI; RV32 has no fstat at all and reads
  a size through statx.  Each is a field, discovered by strace and
  parked in the descriptor.
- **A shared register is a shared hazard.**  The driver aliases an
  overflow flag's cell with an operand's in saturating multiply, so
  the memory-cell targets must compute and park the product before
  the flag lands; the register targets were immune only by accident.
  And the rv32 startup clobbered argc with the register it borrowed
  to zero a cell's high half — one line, and both env and auxv went
  blank until it moved.

## The Lexer's Future: the Mask Pipeline

The current lexer is the scalar, table-driven shape of a design meant
to vectorize.  The researched plan for the native/SIMD/GPU lexer, so
attempt 3+ can build toward it:

1. **Phase A over 64-byte blocks**: classify bytes into ≤8 classes
   with two nibble `pshufb` lookups; build one `u64` mask per class;
   derive run boundaries with shift/AND/XOR (`starts = m & ~(m<<1)`),
   string interiors by prefix-XOR (`clmul`), escapes by the
   odd-backslash carry trick; validate UTF-8 in the same pass with the
   Lemire–Keiser three-lookup scheme (~13 GiB/s reported).  All
   cross-block state is a few bits of scan carry — the property that
   makes the same dataflow run on GPUs (masks↔ballots, clmul↔scan).
2. **Phase B**: turn the token-start mask into an index array with
   `tzcnt`/`blsr`, eight at a time straight-line.
3. **Scalar fallback**: the same phases with SWAR on `u64`, and a
   **shift-based DFA** for validation — the whole transition row
   packed per input byte, `state = table[byte] >> (state & 63)`, fully
   branchless at ~1 byte/cycle.
4. **Boundaries**: byte offsets everywhere; character columns computed
   on demand by popcount of lead bytes (`movemask` + `popcnt`), never
   tracked in the hot loop.  Today's lexer already stores byte offsets
   and derives columns; it just does so per byte.
5. **Keywords**: today one hash probe; natively, padded 8/16-byte
   images compared with one masked load + `cmov` of the token id.

## `@wrap` in the Compiler's Own Source

`@wrap` says that arithmetic is meant to run off the end of its type,
and so suppresses the overflow report.  That makes an unnecessary one
worse than noise: it switches off a check over whatever it encloses.
A sweep of the source left eleven, and each of them wraps on purpose:

- `i64_str` works below zero, because `0 - n` for the most negative
  `i64` is the one negation that has no answer;
- the lexer accumulates a `u64` literal past `i64` deliberately — the
  bit pattern *is* the value, and the sign is how the reader learns
  the literal is a big one;
- `fold_bin` computes the wrapped result precisely so it can compare
  it against the operands and *report* the overflow itself;
- `fnv1a`'s multiply is meant to run off the end of the word, since
  that is what mixes the bits;
- and two literal negations at the type's edge, where nothing wraps
  today but the one value that would is one a program may write.

Everything else was reflex.  A bitwise mask cannot overflow, so
`@wrap(v) & 255` was wrapping nothing; `0 - 100` and `0 - 1` are
negative constants, written `⁻100` and `⁻1`; `0 - (1 « (bits - 1))`
sits behind a guard that has already returned for the 64-bit case;
and slot and index arithmetic like `0 - slot - 2` is nowhere near an
edge.  Removing those restores the checking they were switched off
over, which is the whole point of the annotation being explicit.

## Contracts in the Compiler's Own Source

Per the policy in CLAUDE.md, the compiler practices what it compiles:
helpers carry `@pre`/`@post` — admissible ranges on the type
constructors, alignment and coverage promises on `align_up` and
`build_elf`, condition-code bounds on `cc_of` — and the larger
functions assert their internal milestones: token, node and IR arrays
still in step when a stage hands off, every parameter owning a slot,
every jumped-to label placed before its fixup patches (the assertion
that would have caught a real begin_fn miscount), every function
leaving a code offset behind.  The one recorded exception: the `ty_*`
accessors run for every node the checker touches, so their encoding
invariants are enforced at the constructors rather than per read.
The whole set costs ~3.5% under the interpreter, measured.

## Diagnostics and the Decision Log

The parser recovers at line boundaries (a misparsed statement is
dropped, its hanging block skipped whole, and parsing resumes on the
next line — capped at twenty errors), so one run reports many
mistakes.  Every diagnostic prints its source line with a
character-aligned caret, decoded from UTF-8.  `--diag=json` renders
the same records as JSON; `--log=json` emits the lowering's decisions
— `value-table`, `jump-table`, `ladder-kept` (with cases and span),
`select`/`branched-conditional`, `eager-logic`/`short-circuit` — one
JSON object each with function and line, which is the edit-eval-check
brief's requirement that a program never parse prose.

## The Bootstrap Chain

`build/bootstrap.sh` runs the chain the process prescribes: the
interpreted compiler builds stage 1 (minutes), stage 1 builds
stage 2 (49 ms), stage 2 builds stage 3, and stages 2 and 3 must
match byte for byte before the verified stage-2 binary installs as
`build/ngplc`.  Stage 1 matches them too: the compiler is
deterministic whichever way it runs.  The build caches against the
newest of the sources, so the suite's native runs find it ready.

Stage 1 is where the whole chain's time goes, and how long it takes is
a property of the machine rather than of the compiler; the figure below
is what a profile-driven campaign left, measured where it was run.

The 2¼ minutes is the residue of a profile-driven campaign on the
tree-walking interpreter, run entirely with its own instruments
(`--timeout`, `--heartbeat`, `--fn-stats`) after the first
self-compile attempts either looped or crawled:

- two quadratics fell — per-call re-coercion of every array element
  (memoized type parsing, element types stamped in place) and the
  by-value array copy (read-only parameters alias; every write path
  through them is refused, so the copy bought nothing)
- the two fifty-case `isinstance` ladders became one-probe dictionary
  dispatch on the node's class, the handlers extracted mechanically
  by an `ast` analysis that accepts only blocks whose every path
  returns or raises
- foreach walks an array's live list rather than a copy — which is
  also what the compiled code does — and the common small values
  (integers, the two booleans, ∅) are pooled singletons

Each batch was gated on the full suite and on the stage-1 binary
staying byte-identical.  The arc: unbounded → 7 min → 4m10s → 2m58s
→ 2m18s.

A second campaign, after the compiler had grown to twenty-five files,
took another **12.8%** (8m40s → 7m34s, measured back to back on one
machine, both halves producing the same binary byte for byte).  What
it found was not where reading the code suggested it would be:

- The first batch was drawn from reading the call path — per-call list
  copies, a set comprehension rebuilt on each of eleven million calls
  — and bought **0.25%**.  The cost is per *node*, not per call.
- `cProfile` charges a fixed price to every call, and this workload
  makes eleven million of them, so what it reports is partly a picture
  of itself; a ninety-second window over a nine-minute run is also all
  loading and lexing, and nearly sent the work after a `UnitValue`
  path that the whole-run data showed was irrelevant to it.  A
  two-millisecond **sampler** — a thread reading `sys._current_frames`
  — costs nothing per call and covers the whole run, and every real
  finding came from it.
- What it found: `_is_bare_generic` ran `import re` and a
  string-pattern `re.fullmatch` for **every parameter of every call
  and every return**, 2.6% of the run in a program that names no
  generic; every statement allocated a list to hold resources that
  only files ever produce; fifty-five expression handlers computed a
  source position the dispatcher had already recorded and none of them
  read; `same_dimension` built two dictionaries to compare measures
  that are usually the same shared object.

The lesson is the one the first campaign also records, and it is worth
keeping: measure the whole workload with an instrument that does not
change it.

## Testing

One suite (`tests/run_tests.sh`): bootstrap-language tests run under
the interpreter; the shared programs in `tests/compile/` run under
the interpreter **and** compiled, outputs and exit codes diffed — the
strict-subset rule made executable.  `--impl=` selects a side:
`bootstrap`, `compiled` (ngplc under the interpreter), `native` (the
self-hosted `build/ngplc`, the whole sweep in ~2.4 s), `both` (the
default) or `all`.  Thirty-three shared programs cover the whole
core-2 surface including the stopping paths, and seven bootstrap test
files whose whole `@test` surface sits inside the subset run as
shared tests besides: compiled, run with `--test`, and their stdout,
stderr and exit code must match the interpreter's byte for byte.
That list grows as the subset grows — most of the other 89 files
lean on features the subset refuses by name (floats, generics,
combinators, custom units, comptime), which is what keeps them
bootstrap-only.  `std.implementation` conditionalizes where
implementations may differ.  The diff has
caught real bugs on both sides, including the interpreter's
float-precision division and the hash type band hiding inside the
array band.

## Sources

Branchless/codegen: Torvalds on cmov (yarchive), QuestDB cmov-vs-branch
measurements (Zen 4), LLVM `X86CmovConversion`/`SelectOptimize`/
SimplifyCFG thresholds and `isSafeToSpeculativelyExecute`, GCC ifcvt
params and switch clustering (`case-values-threshold`, density ratios),
Wennborg "switch lowering improvements", abseil Swiss tables, folly
F14, CERT As-if-Infinitely-Ranged model, MaskRay "All about UBSan",
warp-divergence characterization (arXiv:2607.23402), Co-dfns, Pareas.
UTF-8/tokenization: Höhrmann's DFA decoder, Pervognsen shift-based
DFAs, Keiser & Lemire "Validating UTF-8 In Less Than One Instruction
Per Byte" (arXiv:2010.03090, simdutf), Langdale & Lemire "Parsing
Gigabytes of JSON per Second" (arXiv:1902.08318, simdjson stage 1),
simdzone design notes, gperf, Lemire on small-set string recognition,
cuDF's GPU FST tokenizer and cuJSON, Mytkowicz et al. data-parallel
FSMs, Levien's stack-monoid GPU parsing notes.
