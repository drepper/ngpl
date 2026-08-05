Creating a New Programming Language with Support for Automatic Code Generation
==============================================================================

Introduction
------------

This project documents the design and implementation of a new programming language built from the ground up. The language is conceived around a single guiding principle: **code should expose its intentions clearly enough to be understood, reviewed, and verified by humans, while remaining efficient enough for production use.**

### Goals

The language pursues several interrelated goals:

- **Static detection of problems.** Many classes of errors — type mismatches, unit inconsistencies, unsafe operations — are caught at compile time. The language encourages programmers to express contracts, assertions, and invariants that the compiler can check automatically.
- **Efficient execution.** When the programmer provides additional type information, annotations, and structural constraints, the compiler generates tight machine code. The same source can also run in an interpreted mode with boxed values for scripting and rapid development.
- **Human-understandable descriptions.** Contracts and assertions are not mere boilerplate; they serve as living documentation. The language generates readable summaries of program properties directly from the source.
- **Composability.** Functions are first-class objects. The language supports functional programming patterns, combinator-style pipelines, currying, and higher-order functions alongside imperative and concurrent styles.

### Language Features

The language itself is designed around a set of foundational choices:

- **Type system** supporting strict ( Hindley-Milner-like) and scripting modes, sum and product types with pattern matching, unit annotations for physical quantities, optional types, and rich numeric hierarchy including arbitrary-precision integers, floating-point types at various precisions, and rational numbers.
- **Expression syntax** optimized for clarity: no operator precedence confusion (experiments will determine the final approach), Unicode operators where expressive, and a consistent distinction between variable definitions and assignments.
- **Concurrency primitives** including gang execution, job-based parallelism, channels inspired by Occam and Go, and first-class coroutines — all with kernel-level support.
- **Memory management** without garbage collection: either explicit lifetime control (akin to Rust) or reference-counted boxed values, with stack allocation preferred when lifetimes are local.
- **Domain-specific constructs** for arithmetic on vectors, matrices, and tensors; sparse and specialized data structures; compile-time computation (`comptime`); and a hygienic macro system.

### The Interpreter

The interpreter serves as both a development environment and the bootstrap implementation of the language:

- A **REPL** supports interactive function calls, variable inspection, and incremental code loading.
- Functions are **JIT-compiled** as they are used, with fallback to interpretation for rapid iteration.
- The interpreter exposes internal state — parse trees, type information, generated intermediate representations — enabling tools that visualize and analyze code.
- It bootstraps the language: the full compiler is written in the language itself, with the interpreter serving as the initial compilation target.

### The Compiler

The compiler transforms source into efficient machine code:

- **Ahead-of-time (AOT) compilation** produces executables linked against a minimal runtime.
- **Ahead-of-time compilation to GPU targets** (e.g., Vulkan) for accelerated compute workloads.
- A **language server protocol (LSP)** mode powers editor integration, exposing types, contracts, and analysis results to IDEs and tools.
- Compilation is designed for **high parallelism and fast startup**, supporting rapid edit-eval-check cycles.

### The Runtime

The runtime is intentionally minimal and purpose-built:

- **Asynchronous I/O** built on `io_uring` (Linux) for high-throughput, low-latency operations.
- **Direct kernel interfaces** — `clone3`, futex, and similar syscalls — rather than abstraction layers.
- **Modular initialization**: only the runtime components actually used by a program are loaded and initialized.
- **Address spaces** as first-class language concepts, with configurable access costs and protection attributes.

### How It All Fits Together

The interpreter and compiler share a common front-end (scanner, parser, type checker) but diverge in their back-ends. The runtime provides the foundation for execution, I/O, concurrency, and memory management. All three components — language, tools, and runtime — are documented here as they are designed and implemented.

### Document Structure

This document is organized into chapters, each covering a distinct aspect of the language design and implementation:

1. **Lexical Analysis** — character encoding, Unicode handling, identifiers, literals, operators, comments, and macros
2. **Parsing and Syntax** — grammar design, context-free requirements, statement and expression syntax, scoping rules
3. **Type System** — base types, sum and product types, optional types, units, generics, type inference
4. **Expressions and Operators** — arithmetic, logical, boolean operations, casting, function calls, currying, combinators
5. **Functions and Control Flow** — definitions, purity, closures, lambdas, conditionals, loops, coroutines, lazy evaluation
6. **Concurrency and Address Spaces** — gangs, jobs, channels, execution contexts, address space model, memory sharing
7. **Data Structures** — vectors, matrices, tensors, maps, sets, strings, slices, views, sparse and specialized forms
8. **Modules and Build System** — module system, compilation units, build function, dependency management, SBOM generation
9. **Contracts, Assertions, and Documentation** — contract syntax, invariant checking, test integration, generated documentation
10. **Memory Management** — ownership, lifetimes, reference counting, stack allocation, explicit control
11. **Compile-Time Computation** — `comptime` semantics, metaprogramming, reflection, macro system, code generation
12. **The Interpreter** — architecture, REPL, JIT compilation, internal representations, debugging interfaces
13. **The Compiler** — front-end, optimization passes, code generation, GPU targets, LSP mode
14. **The Runtime** — asynchronous I/O, concurrency primitives, address spaces, memory allocator, startup sequence

Each chapter contains design questions, experiments with concrete examples, results, and final decisions. The reference sections within each chapter serve as the normative specification for that aspect of the language.


Chapter 3: Type System — Integer Types and Untyped Constants
------------------------------------------------------------

### Integer Types

The language provides fixed-width integer types with explicit signedness and bit count.  The naming convention uses a single letter (`i` for signed, `u` for unsigned) followed by the bit width:

| Type  | Width  | Range |
|-------|--------|-------|
| `i8`  | 8-bit  | -128 to 127 |
| `u8`  | 8-bit  | 0 to 255 |
| `i16` | 16-bit | -32768 to 32767 |
| `u16` | 16-bit | 0 to 65535 |
| `i32` | 32-bit | -2³¹ to 2³¹-1 |
| `u32` | 32-bit | 0 to 2³²-1 |
| `i64` | 64-bit | -2⁶³ to 2⁶³-1 |
| `u64`   | 64-bit | 0 to 2⁶⁴-1 |
| `usize` | platform | 0 to 2^N-1 (N = pointer width) |

`usize` is an unsigned integer type whose width matches the platform's pointer size, equivalent to `size_t` in C/C++.  On a 64-bit platform it is 64 bits wide.  It is the natural type for array indices, byte offsets, and object sizes.

Additionally, `int` denotes an arbitrary-precision integer with no fixed width.  This type can represent any integer value regardless of magnitude.

### Untyped Integer Constants

Integer literals in source code are of type **`untyped int`**.  An untyped integer is not yet committed to any specific integer type — it is a compile-time value that can be implicitly coerced to any integer type whose range can represent the value.

This concept is similar to Go's untyped constants and Odin's untyped integers.  The key properties are:

1. **Implicit coercion.**  An `untyped int` value can appear wherever a typed integer is expected.  The coercion is valid if the value fits in the target type's range.  For example, the literal `42` can be used as `u8`, `i32`, `u64`, or any other integer type.

2. **Compile-time range check.**  If a literal value does not fit in the target type, this is a compile-time error.  For example, `300` cannot be coerced to `u8` (max 255).

3. **Arithmetic on untyped integers.**  When two `untyped int` values are combined with an arithmetic operator, the result is also `untyped int` with arbitrary precision — no overflow occurs.  This allows compile-time constant expressions to compute exact results regardless of magnitude.

4. **Type inference with `var name := expr`.**  When a variable is defined with `:=` (no explicit type) and the initializer is an `untyped int`, the variable's type is `int` (arbitrary-precision).  To get a fixed-width type, use the explicit form: `var name : u32 = expr`.

5. **Array initialization.**  In `var name : u32[64] = 0`, the `0` is an `untyped int` that coerces to the array's element type `u32`.

### Examples

```
const K : u32 = [1116352408, 1899447441, ...];   /* array of u32, literals coerced */
var blk_off : usize = 0;                           /* usize variable for byte offsets */
var rem : usize = data_size % 64;                  /* remainder operator, result coerced to usize */
var i : u32 = 0;                                   /* u32 loop counter */
var hash := 0;                                     /* int (arbitrary-precision), inferred from untyped int */
var W : i32[64] = 0;                               /* array of 64 i32 elements, each initialized to 0 */
```

### Design Rationale

The `untyped int` approach avoids requiring suffixes on every integer literal (as in Rust's `42u32` or C++'s `42UL`) while still permitting precise type control through variable declarations.  It keeps the common case — writing plain numbers — clean and readable, while the type system ensures that values fit their containers at compile time.

This design also enables the arbitrary-precision `int` type to coexist naturally with fixed-width types: a literal `256` in a context expecting `u8` is a compile error, but the same literal in an untyped context simply represents the mathematical integer 256.

### Integer Remainder

The `%` operator computes the integer remainder with truncation toward zero, matching C, C++, and Rust semantics:

    a % b = a - trunc(a / b) * b

The result type follows the same rules as other arithmetic operators: `resolve_width` selects the wider operand's type.  For unsigned types, the result is always non-negative.


### Function Return Values

The `return` keyword is used for early returns from a function — exiting before the end of the function body.  For the final expression in a function body, the `return` keyword is optional: the last expression in the body, written without a trailing semicolon, is the function's return value.

This is consistent with expression-oriented languages like Rust, Haskell, and Zig where the last expression in a block is its value.  The rule is:

1. **Explicit return.**  `return expr;` exits the function immediately with the given value.  Required for early returns (e.g., inside an `if` branch before the end of the function body).

2. **Implicit return.**  The last statement in a function body, if it is a bare expression without a trailing semicolon, becomes the function's return value.  No `return` keyword is needed.

3. **Semicolon distinction.**  A trailing semicolon after the last expression discards its value — the function returns `none`.  Omitting the semicolon makes the expression the return value.  This mirrors Rust's semicolon semantics.

Eliding the `return` keyword only really comes into its own when functions are small and can be written
in possibly just a single function.  Requiring the use `return` in an inline-defined anonymous function
would require a significant amount of the total number of tokens for this construct.


#### Examples

```
fn add(a : int, b : int) -> int:
    a + b

fn abs(x : int) -> int:
    if x < 0: return -x
    x

fn greet(name) -> none:
    std.print("hello " + name);
```

In `add`, the expression `a + b` (no semicolon) is the implicit return value.  In `abs`, the early return uses `return`; the final `x` is an implicit return.  In `greet`, the semicolon after `std.print(...)` discards the result, so the function returns `none`.

The same functions can equivalently be written with braces:

```
fn add(a : int, b : int) -> int { a + b }
fn abs(x : int) -> int { if x < 0 { return -x; } x }
```


### Optional Types and the `?` Operator

A function that may fail to produce a value declares an **optional return type** by prefixing the type with `?`.  The optional type `?T` can hold either a value of type `T` (wrapped in `some`) or `none` (absence of a value).

#### Declaration

```
fn get_padded_byte(data, pos : usize, data_size : usize, total_size : usize) -> ?u8:
    if pos >= total_size: return none
    if pos < data_size: return data.getbyte(pos)
    ...
    0
```

A function with return type `?u8` auto-wraps non-`none` return values in `some`.  Returning `none` explicitly signals absence.  The caller receives either `some(value)` or `none`.

#### The `?` Postfix Operator

The `?` operator unwraps an optional value or **propagates** `none` to the enclosing function:

```
fn get_padded_word(data, off : usize, data_size : usize, total_size : usize) -> ?u32:
    var b0 : u32 = get_padded_byte(data, off, data_size, total_size)?
    ...
```

Semantics of `expr?`:

1. If `expr` evaluates to `some(v)`, the `?` expression evaluates to `v`.
2. If `expr` evaluates to `none`, the enclosing function immediately returns `none`.
3. If the enclosing function does not have an optional return type (`?T`), using `?` is a **compile error**.

This matches Rust's `?` operator.  The compile-time restriction ensures that `none` propagation is always visible in the function signature — a function that cannot fail cannot silently swallow failures from callees.

#### The `??` Nil-Coalescing Operator

The `??` operator provides a default value when an optional is `none`:

```
var b0 : u32 = get_padded_byte(data, off, data_size, total_size) ?? 0;
```

Semantics of `expr ?? default`:

1. If `expr` evaluates to `some(v)`, the expression evaluates to `v`.
2. If `expr` evaluates to `none`, the expression evaluates to `default`.
3. The right-hand side is evaluated lazily — only when the left is `none`.

Unlike `?` which propagates `none`, `??` recovers from it.  This is the right choice when absence has a known substitute value rather than being an error.

#### Type Widening on Assignment

When the unwrapped value has a narrower unsigned type than the target variable, implicit widening is permitted.  For example, `get_padded_byte` returns `?u8`; after `??` or `?` produces a `u8` value, assigning it to a `u32` variable widens it.  This is safe because every `u8` value is representable as `u32`.

#### Example: Combining `?` and `??`

A function that returns `none` for absent data, a caller that substitutes a default, and an outer function that propagates structural failure:

```
fn get_padded_byte(...) -> ?u8:
    if pos >= total_size: return none
    ...
    none                                         /* zero-padding zone */

fn get_padded_word(...) -> ?u32:
    if off >= total_size: return none             /* fully out of range */
    var b0 : u32 = get_padded_byte(...) ?? 0     /* absent bytes → 0 */
    var b1 : u32 = get_padded_byte(...) ?? 0
    var b2 : u32 = get_padded_byte(...) ?? 0
    var b3 : u32 = get_padded_byte(...) ?? 0
    (b0 « 24) | (b1 « 16) | (b2 « 8) | b3

fn sha256(data) -> ?int:
    ...
    W[i] ← get_padded_word(...)?                 /* propagates none */
    ...
    hash
```

`get_padded_word` uses `??` to substitute 0 for absent bytes (zero-padding), while using `?` is unnecessary here — absent individual bytes are expected, not erroneous.  `sha256` uses `?` to propagate `none` from `get_padded_word`, which only returns `none` for entirely out-of-range positions.

#### Design Rationale

| Feature | Rust | Zig | Swift | This language |
|---------|------|-----|-------|---------------|
| Optional type | `Option<T>` | `?T` | `T?` | `?T` |
| Propagation | `?` operator | `orelse` / `catch` | — | `?` operator |
| Default value | `.unwrap_or(v)` | `orelse` | `??` | `??` operator |
| Compile-time check | Yes (must return `Result`/`Option`) | Yes | — | Yes (must return `?T`) |
| Auto-wrapping | No (explicit `Some`) | No | No | Yes (return value auto-wrapped) |

The auto-wrapping of return values simplifies the common case: a function returning `?u8` can write `return 42;` instead of `return some(42);`.  The compiler handles the wrapping.  Only `none` must be written explicitly, since it represents a deliberate absence rather than a normal value.


### Function Parameter Types

Function parameters can be annotated with a type using the `name : type` syntax.  When a type annotation is present, the interpreter enforces type compatibility at each call site: arguments are coerced to the declared type, and a type mismatch is a runtime error.  Parameters without type annotations accept any value.

#### Valid Parameter Types

Only built-in types are currently accepted as parameter types:

| Category | Types |
|----------|-------|
| Signed integers | `i8`, `i16`, `i32`, `i64` |
| Unsigned integers | `u8`, `u16`, `u32`, `u64`, `usize` |
| Arbitrary-precision | `int` |
| Other | `bool`, `none` |
| Optional | `?` prefix on any of the above (e.g., `?u32`, `?bool`) |

Using an unknown type name is a compile error (caught when the function definition is processed, before any call).

#### Type Coercion Rules

When an argument is passed to a typed parameter:

1. **Integer types.**  The argument must be an `IntValue`.  It is coerced to the target width using the same wrapping rules as variable definitions — unsigned types mask, signed types sign-extend.  An `int` (arbitrary-precision) argument passed to a `u32` parameter is wrapped to 32 bits.

2. **`bool`.**  The argument must be a `BoolValue`.  No implicit conversion from integers.

3. **`none`.**  The argument must be `NoneValue`.

4. **Optional types (`?T`).**  Three cases:
   - `none` passes through as `NoneValue`.
   - A `some(v)` value has its inner value coerced to `T`.
   - A plain (non-optional) value of type `T` is automatically wrapped in `some`.

#### Examples

```
fn get_padded_byte(data, pos : usize, data_size : usize, total_size : usize) -> ?u8:
    ...

fn expand_s0(prev : u32) -> int:
    (prev ↻ 7) ^ (prev ↻ 18) ^ (prev » 3)

fn maybe_use(value : ?int) -> none:
    ...
```

In `get_padded_byte`, the `data` parameter is untyped (accepts any value, such as a `Bytes` object), while the position and size parameters are enforced as `usize`.  In `expand_s0`, the `prev` parameter is coerced to `u32`, ensuring rotation operations use 32-bit semantics.  In `maybe_use`, the parameter accepts either a plain integer (auto-wrapped to `some`) or `none`.

#### Design Rationale

Parameter type enforcement catches type errors early and enables the interpreter to coerce values to the correct width automatically.  Leaving the type annotation optional preserves the scripting-mode flexibility: untyped parameters accept any value, which is useful for generic functions and for parameters whose types are not yet part of the built-in set (such as user-defined structs or standard library objects like `Bytes`).

| Feature | Rust | Zig | Python | This language |
|---------|------|-----|--------|---------------|
| Parameter types | Required | Required | Optional (hints only) | Optional (enforced when present) |
| Coercion | No (explicit conversion) | No | N/A | Yes (integer widening) |
| Optional params | `Option<T>` | `?T` | `T \| None` | `?T` |
| Unknown type | Compile error | Compile error | Runtime (if checked) | Compile error |


### Block Scoping: Braces and Layout

Blocks of statements — function bodies, if/elif/else branches, while loop bodies — can be delimited in two ways.  Both styles are fully interchangeable and can be freely mixed within a single source file or even within a single function.

#### Brace-Delimited Blocks

The traditional approach uses `{` and `}` to delimit blocks:

```
fn abs(x : int) -> int {
    if x < 0 { return -x; }
    x
}
```

Braces enclose zero or more statements.  Statements are separated by newlines or semicolons.  Indentation inside braces is not significant — it is conventional but not enforced by the parser.

#### Layout-Driven Blocks

A colon `:` at the end of a construct header introduces a layout-driven block, where indentation determines the block's extent:

```
fn abs(x : int) -> int:
    if x < 0: return -x
    x
```

The rules are:

1. **Block introduction.**  A `:` after a function signature, `if`/`elif`/`else`, or `while` opens a layout block.

2. **Indentation.**  The first indented line after `:` establishes the block's indent level.  All subsequent lines at that level (or deeper) are part of the block.  A line at a shallower level ends the block.

3. **Uniform indentation character.**  Within a file, indentation must use either all spaces or all tabs — mixing is a lexer error.  This matches Python 3's rule.

4. **Single-line form.**  A statement on the same line as `:` is a single-statement block:
   ```
   if x < 0: return -x
   ```

5. **Line continuation.**  A trailing binary operator (`+`, `-`, `*`, `/`, `%`, `|`, `&`, `^`, `<<`, `>>`, `«`, `»`, `↺`, `↻`, `==`, `!=`, `<`, `>`, `<=`, `>=`, `??`, `←`, `and`, `or`) or a trailing `=` (in variable definitions) signals that the expression continues on the next line.  The indentation of the continuation line does not create a new block:
   ```
   W[j] ← W[j - 16] + expand_s0(W[j - 15]) +
           W[j - 7] + expand_s1(W[j - 2])
   ```

6. **Nesting suppression.**  Inside parentheses `()` and brackets `[]`, indentation changes are ignored — no block boundaries are introduced.  This allows multi-line function arguments and array literals to be freely indented.

#### Mixed Mode

Brace and layout blocks can be mixed freely.  A function body can use `:` while an inner `if` uses `{ }`, or vice versa:

```
fn mixed(x : int) -> int:
    if x > 10 {
        return x - 10;
    }
    x

fn mixed2(x : int) -> int {
    if x > 10:
        return x - 10
    x
}
```

This flexibility allows programmers to choose the style that best fits each situation — layout for clean, short blocks; braces for complex nesting or when explicit delimiters improve readability.

#### Design Rationale

| Feature | Python | Haskell | Rust | This language |
|---------|--------|---------|------|---------------|
| Layout blocks | Required (no braces) | Optional (`where`, `let`, `do`) | No | Optional |
| Brace blocks | No | Optional | Required | Optional |
| Mixed mode | No | Yes | No | Yes |
| Indent char | Spaces only (tabs allowed but not mixed) | Spaces only | N/A | Spaces or tabs (not mixed) |
| Block start | `:` | layout keywords | `{` | `:` or `{` |

The dual-mode approach draws from Haskell's optional layout rule while using Python's `:` syntax for familiarity.  The key advantage over Python is that braces remain available — useful for single-line blocks, machine-generated code, and situations where explicit delimiters reduce ambiguity.  The key advantage over Rust is that the common case of simple, sequential blocks needs no closing delimiter.


### Foreach Loop

The `foreach` loop iterates over **ranges** and **containers**, binding one or more loop variables that are constant within the loop body.

#### Syntax

```
foreach var1 [: type1] [, var2 [: type2] ...] = expr1 [, expr2 ...] block
```

The `=` separates the variable list from the iterable expressions.  The block uses either `:` (layout) or `{ }` (braces), like all other block constructs.

#### Ranges

A range expression `start…end` (using the `…` character) generates an inclusive sequence of integers:

```
foreach i = 1…10:
    std.print(i)            /* prints 1, 2, 3, ..., 10 */

foreach j = 5…1:
    std.print(j)            /* prints 5, 4, 3, 2, 1 */
```

The direction is determined by comparing `start` and `end`: ascending if `start ≤ end`, descending otherwise.  The type of the loop variable is **untyped int** — its actual integer width is decided by the context in which it is used, not committed to `int` at the range site.

#### Typed Variables

Loop variables can carry type annotations to coerce range values to a specific width:

```
foreach k : u32 = 0…255:
    ...
```

#### Multiple Variables and Iterables

When the number of variables matches the number of expressions, each variable iterates over its corresponding iterable:

```
foreach i, j = 1…5, 10…14:
    /* i takes values 1,2,3,4,5 and j takes values 10,11,12,13,14 */
    ...
```

#### Wrapping Shorter Ranges

The loop runs for as many iterations as the **longest** iterable.  Shorter iterables wrap around from the beginning:

```
foreach i, j = 1…6, 10…12:
    /* i: 1, 2, 3, 4, 5, 6          (6 iterations) */
    /* j: 10, 11, 12, 10, 11, 12    (wraps after 3) */
    ...
```

#### Single Variable with Multiple Iterables — Tuples

When there is exactly **one** variable but **multiple** iterable expressions, the variable receives a **tuple** containing one element from each iterable at the current position:

```
foreach pair = 1…3, 10…12:
    std.print(pair[0])      /* 1, 2, 3 */
    std.print(pair[1])      /* 10, 11, 12 */
```

Tuple elements are accessed by integer index (`pair[0]`, `pair[1]`).  In the future, access by unique type name will also be supported when the element types are distinct.  Wrapping rules apply to each iterable independently.

#### Container Iteration

In addition to ranges, `foreach` accepts any iterable container (arrays, vectors, etc.):

```
var data := [10, 20, 30, 40]
foreach idx = 0…3:
    total ← total + data[idx]
```

Direct iteration over container elements (without index) will be supported as the container type system matures:

```
/* Future: */
foreach val = data:
    total ← total + val
```

#### Constant Loop Variables

Loop variables are **constant** within the body — they cannot be reassigned or redefined:

```
foreach i = 1…5:
    i ← i + 1          /* ERROR: cannot assign to foreach variable 'i' */
    var i := 99         /* ERROR: cannot redefine foreach variable 'i' */
```

This constraint ensures that the loop's iteration is fully determined by the iterable expressions and cannot be altered by side effects in the body.

#### Examples

Accumulate a sum:
```
var sum := 0
foreach i = 1…100:
    sum ← sum + i
/* sum is 5050 */
```

Two-variable loop with wrapping:
```
foreach row, col = 0…2, 0…3:
    /* row wraps: 0,1,2,0  for 4 iterations (longest range) */
    /* col runs:  0,1,2,3 */
    ...
```

Tuple destructuring by index:
```
foreach point = [1,2,3], [10,20,30]:
    var x := point[0]
    var y := point[1]
```

#### Design Rationale

| Feature | Python | Rust | Zig | This language |
|---------|--------|------|-----|---------------|
| Iteration keyword | `for` | `for` | `for` | `foreach` |
| Range syntax | `range(1, 11)` | `1..=10` | `0..10` | `1…10` (inclusive) |
| Multiple iterables | `zip(a, b)` | `a.zip(b)` | N/A | built-in with wrapping |
| Tuple binding | destructuring | destructuring | N/A | single var → tuple |
| Loop var mutability | mutable | immutable | N/A | immutable |
| Shorter-range behavior | `zip` truncates | `zip` truncates | N/A | wraps around |

The wrapping behavior for shorter ranges is deliberate: it enables patterns like cycling through a palette or repeating a short sequence across a longer one, which are common in array programming languages like APL.  Languages that truncate to the shortest require explicit repetition; wrapping makes the common case trivial.


### Built-in Test System

Unit testing is built into the language, similar to Rust's `#[test]` attribute.  Functions are annotated with `@test` to mark them as test functions.  The annotation accepts an optional list of function names that the test covers.

#### Annotation Syntax

```
@test
fn test_something() -> none:
    ...

@test(sha256)
fn test_sha256_abc() -> none:
    ...

@test(encrypt, decrypt)
fn test_round_trip() -> none:
    ...
```

#### Execution Semantics

Test functions are always run unless explicitly skipped.  Their execution order depends on whether they reference specific functions:

1. **Standalone tests** (`@test` without references) run at startup, before the `@start` function.  If any standalone test fails, the program terminates immediately.

2. **Referenced tests** (`@test(func_name)`) run once, automatically, on the first call to any of the referenced functions.  This follows `pthread_once` semantics: the test executes exactly once regardless of how many times the referenced function is called.  If a test references multiple functions, it runs on whichever is called first.

3. **Test mode** (`--test` flag) runs all tests — both standalone and referenced — without executing the `@start` function.  The interpreter reports results and exits with status 0 (all passed) or 1 (any failed).

4. **Skip mode** (`--skip-tests` flag) suppresses all test execution during normal program runs.  Both standalone tests and referenced tests are skipped; only the `@start` function executes.  This is useful for production runs where test overhead is undesirable.  The `--skip-tests` flag has no effect in `--test` mode.

#### Assertion Functions

Two built-in assertion functions are available in all scopes:

- `assert(condition)` — fails if the condition is `false` or zero.  An optional second argument provides a custom error message: `assert(x > 0, "x must be positive")`.

- `assert_eq(expected, actual)` — fails if the two values differ.  The error message displays both values for easy comparison.  Large integers (such as cryptographic hashes) are displayed in hexadecimal.

#### Test Output

In normal mode, only failing tests produce output — passing tests are silent.  All standalone tests run before aborting, so every failure is reported in one pass.  Referenced tests that fail during execution terminate the program immediately.

In `--test` mode, every test result is printed and a summary follows:
```
running 3 tests
test test_sha256_empty ... ok
test test_sha256_abc ... ok
test test_sha256_448bit ... ok

test result: ok. 3 passed; 0 failed
```

#### Example: FIPS 180-4 SHA-256 Test Vectors

```
@test(sha256)
fn test_sha256_empty() -> none:
    var data := std.bytes("")
    var hash := sha256(data)
    assert_eq(hash, 0xe3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855)

@test(sha256)
fn test_sha256_abc() -> none:
    var data := std.bytes("abc")
    var hash := sha256(data)
    assert_eq(hash, 0xba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad)
```

#### Design Rationale

The test system draws from several languages:

| Feature | Rust | Zig | This language |
|---------|------|-----|---------------|
| Annotation | `#[test]` | `test` block | `@test` / `@test(func)` |
| Runs with program | No (`cargo test` only) | No | Yes (always, unless skipped) |
| Function-level binding | No | No | Yes (`@test(func)` triggers on first call) |
| Assertion | `assert!` macro | `std.testing.expect` | `assert` / `assert_eq` builtins |

The function-level binding via `@test(func)` is unique to this language.  It ensures that a function's tests run before the function is ever used in production, catching regressions at the earliest possible point.  The `pthread_once` execution model ensures no runtime overhead after the first call.

The `std.bytes(string)` function creates a `Bytes` object from a UTF-8 string literal, enabling test functions to construct known inputs for cryptographic and binary data operations.
