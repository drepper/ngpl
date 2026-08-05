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

### Fast Integer Types

For each fixed-width integer type, a corresponding **fast** variant exists that is at least as wide as the base type but may be wider if the platform can operate on the wider type more efficiently.  The naming convention appends `fast` to the base type name:

| Fast type | Minimum width | x86_64 width | Underlying type |
|-----------|---------------|--------------|-----------------|
| `u8fast`  | 8-bit  | 32-bit | `u32` |
| `i8fast`  | 8-bit  | 32-bit | `i32` |
| `u16fast` | 16-bit | 32-bit | `u32` |
| `i16fast` | 16-bit | 32-bit | `i32` |
| `u32fast` | 32-bit | 64-bit | `u64` |
| `i32fast` | 32-bit | 64-bit | `i64` |
| `u64fast` | 64-bit | 64-bit | `u64` |
| `i64fast` | 64-bit | 64-bit | `i64` |

The primary use case is **loop indices and local counters** where the exact width is unimportant but performance matters.  On some 64-bit platforms, 32-bit operations are fastest (due to shorter instruction encodings and implicit zero-extension); on others, native 64-bit operations are faster.  Fast types let the compiler choose the optimal width for the target.

#### Wrapping Behavior

Fast types wrap at the width of their underlying type, not the minimum width.  For example, `u8fast` on x86_64 wraps at 2³² (not 2⁸):

```
var x : u8fast = 255
x ← x + 1
/* x is 256, not 0 — because u8fast is 32-bit on this platform */
```

This means code using fast types must not rely on narrow wrapping behavior.  If wrap-at-8-bit semantics are needed, use `u8` explicitly.

#### Restriction: No Fast Types in Data Structures

Fast types **cannot** be used in data structure definitions that are visible outside function scope.  This prevents platform-dependent memory layouts from leaking across compilation boundaries:

- **Array element types**: `var arr : u8fast[64] = 0` is an error
- **Const definitions**: `const K : u32fast = [...]` is an error
- **Struct/product type members**: not allowed (when implemented)

Fast types **are** allowed for:

- Local scalar variables: `var i : u32fast = 0`
- Loop indices: `foreach k : u32fast = 0…63:`
- Function parameters: `fn f x : u32fast → int:`

#### Design Rationale

This design mirrors C's `uint_fast8_t` family from `<stdint.h>` but with a cleaner naming convention and stricter usage rules.  The C standard allows fast types anywhere, which can lead to surprising behavior when data structures have different sizes on different platforms.  Restricting fast types to local computation prevents this class of portability bugs while preserving the performance benefit for the common case of loop indices.

| Feature | C (`<stdint.h>`) | Rust | Zig | This language |
|---------|-----------------|------|-----|---------------|
| Fast types | `uint_fast8_t` etc. | none | none | `u8fast` etc. |
| Data structure restriction | none | N/A | N/A | enforced |
| Width guarantee | at least N bits | N/A | N/A | at least N bits |
| Naming | verbose | N/A | N/A | `Nfast` suffix |


### The `byte` Type

The `byte` type is an 8-bit unsigned integer (semantically identical to `u8`) used specifically for raw data and I/O operations.  It occupies the range 0 to 255.

While `byte` and `u8` have the same representation and coercion rules, `byte` signals intent: the value represents raw data rather than a numeric quantity.  Arithmetic on `byte` values follows the same wrapping rules as `u8`.


### Integer Overflow Semantics

Integer overflow behavior depends on whether the type is **signed** or **unsigned**:

#### Unsigned Types: Modular Arithmetic

Unsigned types (`u8`, `u16`, `u32`, `u64`, `usize`, `byte`, and all unsigned fast variants) use **modular arithmetic**.  Operations that exceed the type's range silently wrap:

```
var x : u8 = 255
var y : u8 = 1
var z := x + y          /* z is 0 (wrapped modulo 256) */

var a : u32 = 4294967295
var b : u32 = 1
var c := a + b           /* c is 0 (wrapped modulo 2³²) */

var d : u8 = -1          /* d is 255 (modular representation) */
```

This matches C's unsigned semantics and Rust's `Wrapping<T>`.  Algorithms like SHA-256 depend on this behavior.

#### Signed Types: Overflow Aborts

Signed types (`i8`, `i16`, `i32`, `i64`, and all signed fast variants) **abort on overflow**.  Any arithmetic operation that produces a result outside the type's range raises an `OverflowError`:

```
var x : i8 = 127
var y : i8 = 1
var z := x + y           /* ERROR: integer overflow */

var a : i32 = -2147483648
var b := -a              /* ERROR: integer overflow (negation) */
```

This is the default strict mode behavior, as mandated by the language design: "in strict mode arithmetic overflow/underflow must be reported or lead to termination."

#### Untyped `int`: Arbitrary Precision

The untyped `int` type has arbitrary precision — overflow is impossible.  When a typed and untyped integer are combined, the result is `int` (arbitrary precision), so overflow cannot occur in mixed expressions.

#### Coercion Overflow

Assigning an untyped integer literal to a signed typed variable checks that the value fits:

```
var x : i8 = 128         /* ERROR: 128 does not fit in i8 (range -128..127) */
var y : u8 = 256         /* y is 0 (unsigned wraps) */
```

#### Bitwise Operations

Bitwise operations (`&`, `|`, `^`, `~`, `«`, `»`, `↺`, `↻`) always produce wrapped results regardless of signedness, since they operate on the bit representation and the result is always in range after masking.


### Binary Logic Operations

Binary logic operations use Unicode glyphs and operate on logical truth values.  Unlike bitwise operations (which manipulate individual bits), these first reduce each operand to a boolean and then apply the logic function.  The result is always `bool`.

#### Operators

| Glyph | Name | Arity  | Definition |
|-------|------|--------|------------|
| `∧`   | AND  | binary | true when both operands are truthy |
| `∨`   | OR   | binary | true when at least one operand is truthy |
| `⊕`   | XOR  | binary | true when exactly one operand is truthy |
| `⊼`   | NAND | binary | true when not both operands are truthy |
| `⊽`   | NOR  | binary | true when neither operand is truthy |
| `¬`   | NOT  | unary  | true when the operand is falsy |

#### Operand Conversion

For `bool` operands the value is used directly.  For integer operands (`i8`, `u32`, `int`, etc.) a nonzero test is applied: zero maps to `false`, any nonzero value maps to `true`.  Floating-point operands are not allowed and produce a type error.

```
var a : i32 = 42
var b : i32 = 0
a ∧ b                       /* false — 42 is truthy, 0 is falsy */
a ∨ b                       /* true  — at least one is truthy */
¬b                           /* true  — 0 is falsy */
```

#### Precedence

The logic operators follow standard Boolean algebra precedence, all binding tighter than the short-circuit keywords `and`/`or` and looser than comparison operators:

| Tightest → Loosest | Operators |
|---------------------|-----------|
| comparison          | `==`, `!=`, `<`, `>`, `<=`, `>=` |
| logic AND/NAND      | `∧`, `⊼` |
| logic XOR           | `⊕` |
| logic OR/NOR        | `∨`, `⊽` |
| short-circuit AND   | `and` |
| short-circuit OR    | `or` |

This means `a == 0 ∧ b != 0` parses as `(a == 0) ∧ (b != 0)`, and `x ∧ y ∨ z` parses as `(x ∧ y) ∨ z`.

#### Element-wise on Arrays

Like arithmetic operators, the logic operators iterate element-wise over arrays and vectors:

```
var a : i32[3] = 0
a[0] ← 1; a[1] ← 0; a[2] ← 5
var b : i32[3] = 0
b[0] ← 3; b[1] ← 0; b[2] ← 0
var r := a ∧ b              /* [true, false, false] */
```

#### Distinction from Other Operators

| Category | Operators | Semantics |
|----------|-----------|-----------|
| Bitwise  | `&`, `\|`, `^`, `~` | operate on individual bits, result is an integer of the same type |
| Logic    | `∧`, `∨`, `⊕`, `⊼`, `⊽`, `¬` | nonzero test then logic function, result is `bool` |
| Short-circuit | `and`, `or`, `not` | like logic but short-circuit evaluation, result is `bool` |


#### Explicit Wrapping with `@wrap`

The `@wrap(expr)` annotation enables modular arithmetic for all operations within its scope, even for signed types that would normally abort on overflow.  This is useful for cryptographic algorithms and other code that intentionally uses wrapping arithmetic on signed types:

```
var x : i8 = 127
var y : i8 = 1
var z := @wrap(x + y)      /* z is -128 (wraps instead of aborting) */

var a : i32 = -2147483648
var b := @wrap(-a)          /* b is -2147483648 (wraps instead of aborting) */
```

`@wrap` applies to the entire expression within the parentheses, including nested sub-expressions and function arguments.  Operations outside the `@wrap` scope retain their normal overflow behavior:

```
var x : i8 = 127
var y : i8 = 1
var safe := @wrap(x - y)    /* wrapping subtraction */
var z := x + y               /* ERROR: still aborts outside @wrap */
```

For unsigned types, `@wrap` is a no-op since they already use modular arithmetic, but it serves as documentation of intent:

```
/* SHA-256 compression round — u32 additions intentionally wrap. */
const t1 := @wrap(v[7] + s1 + ch + K[t] + W[t])
```

#### Design Rationale

| Feature | C | Rust | Zig | This language |
|---------|---|------|-----|---------------|
| Signed overflow | UB | panic (debug) / wrap (release) | UB / `@addWithOverflow` | abort |
| Unsigned overflow | wraps | wraps | wraps | wraps |
| Compile-time check | sometimes | yes | yes | yes |
| Arbitrary precision fallback | no | no | `comptime_int` | `int` type |

The split between unsigned (wraps) and signed (aborts) reflects a fundamental semantic difference: unsigned types represent bit patterns and modular counters, while signed types represent mathematical integers where overflow is a logic error.  This avoids the undefined behavior of C while being less surprising than Rust's debug/release split.


### Dynamic Arrays as Parameters

Function parameters can be annotated with dynamic array types using the `type[]` syntax:

```
fn process data : byte[] → int:
    ...
```

A dynamic array parameter carries its size implicitly.  The size is accessible via the `.sizeof` property:

```
fn count_bytes data : byte[] → usize:
    data.sizeof
```

#### Fixed-size vs. Dynamic Array Parameters

| Syntax | Meaning |
|--------|---------|
| `data : byte[64]` | Fixed-size array of 64 bytes — a single value |
| `data : byte[]` | Dynamic-size array — carries hidden size, queryable via `.sizeof` |

Fixed-size array parameters behave as a single value of known extent.  Dynamic array parameters behave like a fat pointer: the array data and its length travel together.

#### Coercion

When a `Bytes` object (from file I/O or `std.bytes()`) is passed to a `byte[]` parameter, it is automatically coerced to a byte array.  Each byte becomes an element of type `byte`.

#### Iteration

Dynamic arrays support iteration with `foreach`:

```
fn sum_bytes data : byte[] → int:
    var total := 0
    foreach b := data:
        total ← total + b
    total
```

The loop iterates over each element of the array.  The loop variable is constant within the body (as with all `foreach` variables).

#### Design Rationale

| Feature | C | Rust | Zig | Go | This language |
|---------|---|------|-----|----|---------------|
| Array + size | separate pointer and length | slice `&[u8]` | `[]const u8` | `[]byte` | `byte[]` with `.sizeof` |
| Size access | manual tracking | `.len()` | `.len` | `len(s)` | `.sizeof` |
| Bounds checking | none | runtime panic | optional | runtime panic | planned |

The `.sizeof` property name is chosen to parallel the C/C++ `sizeof` operator while being a property of the array value rather than a compile-time operator.  It returns the number of elements, not the byte size (for `byte[]` these are identical, but for `u32[]` the element count and byte size differ).

The dynamic array type is the natural parameter type for functions that operate on variable-length data: hash functions, encoders, search routines.  The implicit size avoids the error-prone pattern of passing separate data and length parameters.


### Integer Remainder

The `%` operator computes the integer remainder with truncation toward zero, matching C, C++, and Rust semantics:

    a % b = a - trunc(a / b) * b

The result type follows the same rules as other arithmetic operators: `resolve_width` selects the wider operand's type.  For unsigned types, the result is always non-negative.


### Function Definition Syntax

Function definitions use the `fn` keyword followed by the function name, an optional parameter list, an optional return type, and a block body.  The parameter list is **not** enclosed in parentheses — it is terminated by `→` (introducing the return type) or `:` / `{` (introducing the body directly).  The ASCII form `->` is accepted as an alternative to `→`.

#### Grammar

```
fn name [param1 [: type1] [, param2 [: type2] ...]] [→ return_type] block
```

The function name is a single identifier.  Parameters are separated by commas.  Each parameter is an identifier optionally followed by `: type`.  The return type is introduced by `→` (or the ASCII equivalent `->`).  The block is either a layout block (`:`) or a brace block (`{`).

#### Examples

```
fn main → ∅:                              /* no parameters */
    std.print("hello")

fn add a : int, b : int → int:               /* two typed parameters */
    a + b

fn identity x → int:                          /* untyped parameter */
    x

fn sha256 data : byte[] → int?:              /* dynamic array parameter */
    ...
```

#### No-Parameter Functions

Functions with no parameters have nothing between the name and `→` or `:`:

```
fn main → ∅:
    ...

fn test_something → ∅:
    ...
```

#### Disambiguation

The `:` character serves double duty: it introduces a type annotation after a parameter name, and it introduces a layout block.  The parser disambiguates by looking ahead: if `:` is followed by an identifier (a type name), it is a type annotation.  Otherwise, it starts the function body.  Optional (`T?`) and expected (`T?E`) postfixes are parsed after the base type identifier.

This means a no-parameter function with no return type uses `:` directly:

```
fn greet:                                     /* : starts the body */
    std.print("hello")
```

And a single-parameter function uses `:` for the type:

```
fn greet name : string → ∅:               /* first : is type, second : is body */
    std.print(name)
```

#### Design Rationale

Removing parentheses from the parameter list reduces syntactic noise, especially for functions with few parameters.  The `→` and `:` tokens provide unambiguous termination of the parameter list without requiring delimiters.  This is similar to Haskell's function definition syntax, where parameters are separated by spaces with no enclosing delimiters.

| Feature | C/C++ | Rust | Haskell | Python | Zig | This language |
|---------|-------|------|---------|--------|-----|---------------|
| Parameter delimiters | `(...)` | `(...)` | none | `(...)` | `(...)` | none |
| Parameter separator | `,` | `,` | space | `,` | `,` | `,` |
| Return type | trailing or leading | `-> T` | `:: T` | `-> T` | `T` | `→ T` |
| Terminator | `{` | `{` | `=` | `:` | `{` | `:` or `{` |


### Unicode and ASCII Arrow Equivalences

The language uses Unicode arrows as the canonical forms for two syntactic roles:

| Unicode | ASCII | Usage |
|---------|-------|-------|
| `→` (U+2192) | `->` | return type annotation |
| `←` (U+2190) | `<-` | assignment |

Both forms are always accepted.  The lexer normalizes the ASCII forms to their Unicode equivalents, so `fn f x : i32 -> i32:` and `fn f x : i32 → i32:` are identical to the parser.  Similarly, `x <- 5` and `x ← 5` produce the same token.

The Unicode forms are preferred in source code for visual clarity and consistency with the other Unicode operators (`«`, `»`, `↺`, `↻`, `∧`, `∨`, `⊕`, `⍴`, `⧺`).  The ASCII forms exist to support environments where entering Unicode characters is inconvenient.


### Function Return Values

The `return` keyword is used for early returns from a function — exiting before the end of the function body.  For the final expression in a function body, the `return` keyword is optional: the last expression in the body, written without a trailing semicolon, is the function's return value.

This is consistent with expression-oriented languages like Rust, Haskell, and Zig where the last expression in a block is its value.  The rule is:

1. **Explicit return.**  `return expr;` exits the function immediately with the given value.  Required for early returns (e.g., inside an `if` branch before the end of the function body).

2. **Implicit return.**  The last statement in a function body, if it is a bare expression without a trailing semicolon, becomes the function's return value.  No `return` keyword is needed.

3. **Semicolon distinction.**  A trailing semicolon after the last expression discards its value — the function returns `∅`.  Omitting the semicolon makes the expression the return value.  This mirrors Rust's semicolon semantics.

Eliding the `return` keyword only really comes into its own when functions are small and can be written
in possibly just a single function.  Requiring the use `return` in an inline-defined anonymous function
would require a significant amount of the total number of tokens for this construct.


#### Examples

```
fn add a : int, b : int → int:
    a + b

fn abs x : int → int:
    if x < 0: return -x
    x

fn greet name → ∅:
    std.print("hello " + name);
```

In `add`, the expression `a + b` (no semicolon) is the implicit return value.  In `abs`, the early return uses `return`; the final `x` is an implicit return.  In `greet`, the semicolon after `std.print(...)` discards the result, so the function returns `∅`.

The same functions can equivalently be written with braces:

```
fn add a : int, b : int → int { a + b }
fn abs x : int → int { if x < 0 { return -x; } x }
```


### Const Local Variables

The `const` keyword can be used in place of `var` to define a local variable that cannot be modified after initialization:

```
const pi := 3
const max_size : u32 = 1024
```

A `const` variable is initialized exactly like a `var` — with `:=` for type-inferred definitions or `: type =` for explicitly typed ones.  After initialization, any attempt to reassign or redefine the variable is a compile-time (or runtime, in the interpreter) error:

```
const x := 42
x ← 99              /* ERROR: cannot assign to const variable 'x' */
var x := 99          /* ERROR: cannot redefine const variable 'x' */
```

The `const` keyword at function scope is distinct from module-level `const` declarations, which define global constants.  Both prevent modification, but module-level constants are visible across the entire compilation unit while function-scope `const` variables follow normal scoping rules.

`foreach` loop variables are implicitly `const` for assignment — they cannot be reassigned with `←`.  Redefinition with `var` or `const` is permitted but produces a warning (see [Constant Loop Variables](#constant-loop-variables)).

#### Design Rationale

| Feature | C/C++ | Rust | Zig | Go | This language |
|---------|-------|------|-----|----|---------------|
| Local immutability | `const` | default (`let`) | `const` | no | `const` |
| Mutable keyword | (default) | `mut` | `var` | (default) | `var` |

Unlike Rust where immutability is the default (`let` vs `let mut`), this language defaults to mutability (`var`) and opts into immutability (`const`).  This matches C/C++ and Zig conventions and avoids cluttering code with `mut` annotations in imperative-style code where most variables are modified.


### Optional Types (`T?`)

A function that may fail to produce a value declares an **optional return type** by appending `?` to the type name.  The optional type `T?` can hold either a value of type `T` (wrapped in `some`) or `∅` (absence of a value).

#### Declaration

```
fn get_padded_byte data : byte[], pos : usize, total_size : usize → u8?:
    if pos >= total_size: return ∅
    if pos < data.sizeof: return data[pos]
    ...
    0
```

A function with return type `u8?` auto-wraps non-`∅` return values in `some`.  Returning `∅` explicitly signals absence.  The caller receives either `some(value)` or `∅`.

#### The `?` Postfix Operator

The `?` operator unwraps an optional value or **propagates** `∅` to the enclosing function:

```
fn get_padded_word data : byte[], off : usize, total_size : usize → u32?:
    var b0 : u32 = get_padded_byte(data, off, total_size)?
    ...
```

Semantics of `expr?`:

1. If `expr` evaluates to `some(v)`, the `?` expression evaluates to `v`.
2. If `expr` evaluates to `∅`, the enclosing function immediately returns `∅`.
3. If the enclosing function does not have an optional or expected return type (`T?` or `T?E`), using `?` is a **compile error**.

This matches Rust's `?` operator.  The compile-time restriction ensures that `∅` propagation is always visible in the function signature — a function that cannot fail cannot silently swallow failures from callees.

#### The `??` Nil-Coalescing Operator

The `??` operator provides a default value when an optional is `∅`:

```
var b0 : u32 = get_padded_byte(data, off, total_size) ?? 0
```

Semantics of `expr ?? default`:

1. If `expr` evaluates to `some(v)`, the expression evaluates to `v`.
2. If `expr` evaluates to `∅`, the expression evaluates to `default`.
3. The right-hand side is evaluated lazily — only when the left is `∅`.

Unlike `?` which propagates `∅`, `??` recovers from it.  This is the right choice when absence has a known substitute value rather than being an error.

#### Type Widening on Assignment

When the unwrapped value has a narrower unsigned type than the target variable, implicit widening is permitted.  For example, `get_padded_byte` returns `u8?`; after `??` or `?` produces a `u8` value, assigning it to a `u32` variable widens it.  This is safe because every `u8` value is representable as `u32`.


### Expected Types (`T?E`) and Result Handling

An **expected type** `T?E` represents a computation that either succeeds with a value of type `T` or fails with an error of type `E`.  This is the language's counterpart to `Result<T,E>` in Rust and `std::expected<T,E>` in C++26.

#### Syntax

The `?` postfix on a type introduces an optional when no error type follows, and an expected when an error type is named:

| Syntax | Meaning |
|--------|---------|
| `T?` | optional — success (`some(v)`) or absence (`∅`) |
| `T?E` | expected — success (`ok(v)`) or error (`err(e)` where `e` is of type `E`) |
| `T!` | abbreviation for `T?std.errors` |

```
fn safe_div a : int, b : int → int?std.errors:
    (a / b)?
```

Since `std.errors` is the most common error type, the abbreviation `T!` is provided:

```
fn safe_div a : int, b : int → int!:
    (a / b)?
```

`int!` is exactly equivalent to `int?std.errors` — both in parameter types and return types.

#### Constructors

An expected value is either `ok(value)` or `err(error)`:

- **`ok(v)`**: holds a success value.  Functions with an expected return type auto-wrap non-error return values in `ok`, just as optional-returning functions auto-wrap in `some`.
- **`err(e)`**: holds an error value of the declared error type `E`.

#### Division Returns Expected Values

Integer division and remainder (`/`, `%`) return an expected value with error type `std.errors` rather than raising a runtime exception:

```
var x := 10 / 3           /* ok(3) — successful division */
var y := 10 / 0           /* err(std.errors.division_by_zero) */
```

This means division by zero is a **recoverable error** rather than an immediate program abort.  The caller chooses the error-handling strategy:

```
/* Recovery with ?? */
var result := (10 / 0) ?? -1         /* result is -1 */

/* Propagation with ? (requires T?E or T? return type) */
fn compute x : int → int?std.errors:
    var q := (x / 2)?                /* propagates error if x/2 fails */
    q + 10
```

#### The `?` Operator on Expected Values

The `?` postfix operator works on both optional and expected values:

| Input | Behavior |
|-------|----------|
| `some(v)` | evaluates to `v` |
| `∅` | returns `∅` from enclosing function |
| `ok(v)` | evaluates to `v` |
| `err(e)` | returns `err(e)` from enclosing function (if return type is `T?E`) or `∅` (if `T?`) |

The enclosing function must declare a compatible return type; using `?` in a function that returns a plain type is a compile error.

When an expected-error is propagated to a function with an optional return type (`T?`), the error is converted to `∅` — the error detail is discarded.  When propagated to a function with an expected return type (`T?E`), the error is preserved.

#### The `??` Operator on Expected Values

The `??` operator works on both optional and expected values.  For an expected error, the right-hand side provides the fallback:

```
var safe := (x / y) ?? 0            /* 0 on division by zero */
var padded := get_padded_byte(data, pos, total_size) ?? 0  /* 0 on absent byte */
```

| Input | Behavior |
|-------|----------|
| `some(v)` or `ok(v)` | evaluates to `v` |
| `∅` or `err(e)` | evaluates to the right-hand side |

#### Implicit Unwrapping

When an expected value holding `ok(v)` is used in an operation that expects a plain value (arithmetic, comparison, etc.), it is automatically unwrapped to `v`.  An expected value holding `err(e)` raises a runtime error at the point of use:

```
var x := 10 / 3      /* x is ok(3) */
var y := x + 1        /* x auto-unwraps to 3, y is 4 */

var z := 10 / 0       /* z is err(std.errors.division_by_zero) */
var w := z + 1        /* runtime error: unwrap of expected error */
```

This ensures that errors cannot be silently ignored — they must be handled (with `?` or `??`) or they surface at the next use site.

#### Example: Combining `?` and `??`

A function that returns `∅` for absent data, a caller that substitutes a default, and an outer function that propagates structural failure:

```
fn get_padded_byte ... → u8?:
    if pos >= total_size: return ∅
    ...
    ∅                                         /* zero-padding zone */

fn get_padded_word ... → u32?:
    if off >= total_size: return ∅             /* fully out of range */
    var b0 : u32 = get_padded_byte(...) ?? 0     /* absent bytes → 0 */
    var b1 : u32 = get_padded_byte(...) ?? 0
    var b2 : u32 = get_padded_byte(...) ?? 0
    var b3 : u32 = get_padded_byte(...) ?? 0
    (b0 « 24) | (b1 « 16) | (b2 « 8) | b3

fn sha256 data → int?:
    ...
    W[i] ← get_padded_word(...)?                 /* propagates ∅ */
    ...
    hash
```

Expected values and optionals compose naturally: a function returning `T?` can use `?` to propagate errors from callees returning `T?E` — the error is converted to `∅`.  A function returning `T?E` can propagate both expected-errors and optional-nones.

#### Design Rationale

| Feature | Rust | C++26 | Zig | Swift | This language |
|---------|------|-------|-----|-------|---------------|
| Optional type | `Option<T>` | `std::optional<T>` | `?T` | `T?` | `T?` |
| Result type | `Result<T,E>` | `std::expected<T,E>` | `!T` (error union) | — | `T?E` |
| Propagation | `?` operator | — | `try` / `catch` | — | `?` operator |
| Default value | `.unwrap_or(v)` | `.value_or(v)` | `orelse` | `??` | `??` operator |
| Compile-time check | Yes | Yes | Yes | — | Yes (must return `T?` or `T?E`) |
| Auto-wrapping | No (explicit `Some`/`Ok`) | No | No | No | Yes (auto `some`/`ok`) |
| Division error | panic | UB | — | — | `err(std.errors.division_by_zero)` |

The unified `?` syntax for both optional and expected types is intentional: both represent computations that may not produce a value, differing only in whether the failure carries a reason.  The postfix `T?` / `T?E` notation follows Swift's convention for optionals while extending it to expected types — the error type `E` appears naturally after `?`, keeping the syntax compact and context-free.

Division returning an expected value rather than panicking reflects the language's philosophy that errors should be **data**, not **exceptions**.  The caller decides the policy: propagate with `?`, recover with `??`, or let implicit unwrapping catch the error at the next use site.  This is analogous to Rust's approach where division on types implementing `checked_div` returns `Option<T>`, but here the error carries a typed reason (`std.errors.division_by_zero`) via the expected type.


### Function Parameter Types

Function parameters can be annotated with a type using the `name : type` syntax.  When a type annotation is present, the interpreter enforces type compatibility at each call site: arguments are coerced to the declared type, and a type mismatch is a runtime error.  Parameters without type annotations accept any value.

#### Valid Parameter Types

Only built-in types are currently accepted as parameter types:

| Category | Types |
|----------|-------|
| Signed integers | `i8`, `i16`, `i32`, `i64` |
| Unsigned integers | `u8`, `u16`, `u32`, `u64`, `usize` |
| Arbitrary-precision | `int` |
| Other | `bool`, `∅` |
| Optional | `?` postfix on any of the above (e.g., `u32?`, `bool?`) |
| Expected | `?E` postfix where `E` is an error type (e.g., `u32?std.errors`) |
| Expected (short) | `!` postfix, abbreviation for `?std.errors` (e.g., `u32!`) |

Using an unknown type name is a compile error (caught when the function definition is processed, before any call).

#### Type Coercion Rules

When an argument is passed to a typed parameter:

1. **Integer types.**  The argument must be an `IntValue`.  It is coerced to the target width following the integer overflow semantics: unsigned types wrap (modular arithmetic), signed types check and abort on overflow.  An `int` (arbitrary-precision) argument passed to a `u32` parameter is wrapped to 32 bits; the same value passed to an `i32` parameter must fit in the signed range or an `OverflowError` is raised.

2. **`bool`.**  The argument must be a `BoolValue`.  No implicit conversion from integers.

3. **`∅`.**  The argument must be `NoneValue`.

4. **Optional types (`T?`).**  Three cases:
   - `∅` passes through as `NoneValue`.
   - A `some(v)` value has its inner value coerced to `T`.
   - A plain (non-optional) value of type `T` is automatically wrapped in `some`.

5. **Expected types (`T?E`).**  Two cases:
   - An `ExpectedValue` passes through as-is (ok or err).
   - A plain value of type `T` is automatically wrapped in `ok`.

#### Examples

```
fn get_padded_byte data : byte[], pos : usize, total_size : usize → ?u8:
    ...

fn expand_s0 prev : u32 → int:
    (prev ↻ 7) ^ (prev ↻ 18) ^ (prev » 3)

fn maybe_use value : int? → ∅:
    ...
```

In `get_padded_byte`, the `data` parameter is typed as `byte[]` (a dynamic byte array), while the position and size parameters are enforced as `usize`.  In `expand_s0`, the `prev` parameter is coerced to `u32`, ensuring rotation operations use 32-bit semantics.  In `maybe_use`, the parameter accepts either a plain integer (auto-wrapped to `some`) or `∅`.

#### Design Rationale

Parameter type enforcement catches type errors early and enables the interpreter to coerce values to the correct width automatically.  Leaving the type annotation optional preserves the scripting-mode flexibility: untyped parameters accept any value, which is useful for generic functions and for parameters whose types are not yet part of the built-in set (such as user-defined structs or standard library objects like `Bytes`).

| Feature | Rust | Zig | Python | This language |
|---------|------|-----|--------|---------------|
| Parameter types | Required | Required | Optional (hints only) | Optional (enforced when present) |
| Coercion | No (explicit conversion) | No | N/A | Yes (integer widening) |
| Optional params | `Option<T>` | `?T` | `T \| None` | `T?` |
| Unknown type | Compile error | Compile error | Runtime (if checked) | Compile error |


### Block Scoping: Braces and Layout

Blocks of statements — function bodies, if/elif/else branches, while loop bodies — can be delimited in two ways.  Both styles are fully interchangeable and can be freely mixed within a single source file or even within a single function.

#### Brace-Delimited Blocks

The traditional approach uses `{` and `}` to delimit blocks:

```
fn abs x : int → int {
    if x < 0 { return -x; }
    x
}
```

Braces enclose zero or more statements.  Statements are separated by newlines or semicolons.  Indentation inside braces is not significant — it is conventional but not enforced by the parser.

#### Layout-Driven Blocks

A colon `:` at the end of a construct header introduces a layout-driven block, where indentation determines the block's extent:

```
fn abs x : int → int:
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
fn mixed x : int → int:
    if x > 10 {
        return x - 10;
    }
    x

fn mixed2 x : int → int {
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
foreach var1 [: type1] [, var2 [: type2] ...] := expr1 [, expr2 ...] block
```

The `:=` separates the variable list from the iterable expressions, consistent with variable definitions using `var x := expr`.  When a type annotation is present on the last variable, the `:` is consumed by the type syntax, so only `=` follows (e.g., `foreach k : u32 = 0…3:`).  The block uses either `:` (layout) or `{ }` (braces), like all other block constructs.

#### Ranges

A range expression `start…end` (using the `…` character) generates an inclusive sequence of integers:

```
foreach i := 1…10:
    std.print(i)            /* prints 1, 2, 3, ..., 10 */

foreach j := 5…1:
    std.print(j)            /* prints 5, 4, 3, 2, 1 */
```

The direction is determined by comparing `start` and `end`: ascending if `start ≤ end`, descending otherwise.  The type of the loop variable is **untyped int** — its actual integer width is decided by the context in which it is used, not committed to `int` at the range site.

#### Stepped Ranges

A three-part range `start…step…end` iterates from `start` to `end` (inclusive) with the given step size:

```
foreach i := 0…2…10:
    std.print(i)            /* prints 0, 2, 4, 6, 8, 10 */

foreach j := 1…3…10:
    std.print(j)            /* prints 1, 4, 7, 10 */
```

The step can be negative for descending iteration:

```
foreach k := 10…-3…0:
    std.print(k)            /* prints 10, 7, 4, 1 */
```

The step must be a non-zero integer.  The end bound is inclusive: the last value produced is the largest (or smallest, for negative step) value in the sequence that does not exceed the bound.  When the step does not evenly divide the range, the final value may be less than `end`:

```
foreach i := 0…3…10:
    std.print(i)            /* prints 0, 3, 6, 9 (not 10) */
```

Stepped ranges are particularly useful for block-oriented processing:

```
foreach blk_off : usize = 0…64…(total_size - 1):
    /* process 64-byte blocks starting at blk_off */
```

| Syntax | Semantics |
|--------|-----------|
| `a…b` | Inclusive range from `a` to `b`, step 1 (or -1 if `a > b`) |
| `a…s…b` | Inclusive range from `a` to `b`, step `s` |

#### Typed Variables

Loop variables can carry type annotations to coerce range values to a specific width:

```
foreach k : u32 = 0…255:
    ...
```

#### Multiple Variables and Iterables

When the number of variables matches the number of expressions, each variable iterates over its corresponding iterable:

```
foreach i, j := 1…5, 10…14:
    /* i takes values 1,2,3,4,5 and j takes values 10,11,12,13,14 */
    ...
```

#### Wrapping Shorter Ranges

The loop runs for as many iterations as the **longest** iterable.  Shorter iterables wrap around from the beginning:

```
foreach i, j := 1…6, 10…12:
    /* i: 1, 2, 3, 4, 5, 6          (6 iterations) */
    /* j: 10, 11, 12, 10, 11, 12    (wraps after 3) */
    ...
```

#### Single Variable with Multiple Iterables — Tuples

When there is exactly **one** variable but **multiple** iterable expressions, the variable receives a **tuple** containing one element from each iterable at the current position:

```
foreach pair := 1…3, 10…12:
    std.print(pair[0])      /* 1, 2, 3 */
    std.print(pair[1])      /* 10, 11, 12 */
```

Tuple elements are accessed by integer index (`pair[0]`, `pair[1]`).  In the future, access by unique type name will also be supported when the element types are distinct.  Wrapping rules apply to each iterable independently.

#### Container Iteration

In addition to ranges, `foreach` iterates directly over array elements:

```
var data := [10, 20, 30, 40]
var total := 0
foreach val := data:
    total ← total + val
/* total is 100 */
```

This works with any array, including dynamic arrays passed as parameters:

```
fn sum_bytes data : byte[] → int:
    var total := 0
    foreach b := data:
        total ← total + b
    total
```

For dynamic arrays, `foreach` uses the array's `.sizeof` to determine the iteration count.

#### Constant Loop Variables

Loop variables are **constant** within the body — they cannot be reassigned:

```
foreach i := 1…5:
    i ← i + 1          /* ERROR: cannot assign to foreach variable 'i' */
```

Redefinition with `var` or `const` is permitted but produces a **warning**.  The new variable shadows the loop variable for the remainder of the iteration:

```
foreach i := 1…3:
    var i := 99         /* WARNING: redefinition of foreach variable 'i' */
    /* i is 99 here, not the loop counter */
```

This distinction exists because shadowing is a common intentional pattern (e.g., transforming a loop variable into a different form), while assignment would silently alter the loop's iteration semantics.  The warning ensures the programmer is aware of the shadowing.

#### Examples

Accumulate a sum:
```
var sum := 0
foreach i := 1…100:
    sum ← sum + i
/* sum is 5050 */
```

Two-variable loop with wrapping:
```
foreach row, col := 0…2, 0…3:
    /* row wraps: 0,1,2,0  for 4 iterations (longest range) */
    /* col runs:  0,1,2,3 */
    ...
```

Tuple destructuring by index:
```
foreach point := [1,2,3], [10,20,30]:
    var x := point[0]
    var y := point[1]
```

#### Design Rationale

| Feature | Python | Rust | Zig | This language |
|---------|--------|------|-----|---------------|
| Iteration keyword | `for` | `for` | `for` | `foreach` |
| Range syntax | `range(1, 11)` | `1..=10` | `0..10` | `1…10` (inclusive) |
| Stepped range | `range(0, 11, 2)` | `(0..=10).step_by(2)` | N/A | `0…2…10` |
| Multiple iterables | `zip(a, b)` | `a.zip(b)` | N/A | built-in with wrapping |
| Tuple binding | destructuring | destructuring | N/A | single var → tuple |
| Loop var mutability | mutable | immutable | N/A | immutable |
| Shorter-range behavior | `zip` truncates | `zip` truncates | N/A | wraps around |

The wrapping behavior for shorter ranges is deliberate: it enables patterns like cycling through a palette or repeating a short sequence across a longer one, which are common in array programming languages like APL.  Languages that truncate to the shortest require explicit repetition; wrapping makes the common case trivial.


#### Enumerate

The `@enumerate(container)` built-in wraps an iterable so that `foreach` yields `(index, value)` tuples, with the index starting at 0:

```
foreach pair := @enumerate([10, 20, 30]):
    std.print(pair[0], pair[1])      /* 0 10, 1 20, 2 30 */
```

With two loop variables, the tuple is destructured automatically:

```
foreach i, v := @enumerate([10, 20, 30]):
    std.print(i, v)                  /* 0 10, 1 20, 2 30 */
```

`@enumerate` works with arrays, ranges, and any other iterable.  Using `@enumerate` outside a `foreach` context is an error.

| Feature | Python | Rust | Zig | This language |
|---------|--------|------|-----|---------------|
| Enumerate | `enumerate(x)` | `x.iter().enumerate()` | N/A | `@enumerate(x)` |
| Destructuring | `for i, v in enumerate(x)` | `for (i, v) in x.enumerate()` | N/A | `foreach i, v := @enumerate(x)` |


### Anonymous Functions (Lambdas)

Anonymous functions are introduced with the `λ` (U+03BB, GREEK SMALL LETTER LAMDA) keyword.

#### Syntax

```
λ param1 : type1 [, paramN : typeN] [|capture1 [, captureN]|] → ret_type : body
```

- **Parameters**: zero or more comma-separated `name : type` pairs.  Type annotations are mandatory, using the same syntax as function parameters.
- **Return type**: mandatory, specified with `→` (or `->`) followed by a type name.  The `?` and `!` suffixes for optional and error types are supported (e.g., `→ int?`, `→ int!`).
- **Capture list**: optional, enclosed in `|…|`.  Lists the external variables that the lambda body may access.  Must contain at least one name; an empty capture list `||` is a parse error.  Omit the capture list entirely when no captures are needed.
- **Body**: either a single expression after the colon, or a multi-statement block using the same syntax as function bodies (layout-driven with `:` and indentation, or brace-delimited with `{ … }`).  In a multi-statement body the value of the last expression is the return value; explicit `return` is also supported for early exit.

#### Multi-Statement Lambda Bodies

When a lambda body requires more than one expression, use the usual block syntax:

```
// Layout-driven (indented block)
var f := λx : int → int:
    var y := x * 2
    y + 1

// Brace-delimited
var g := λx : int → int: {
    var y := x + 10;
    var z := y * 2;
    z
}
```

Early return is supported inside multi-statement lambda bodies:

```
var clamp := λx : int |lo, hi| → int:
    if x < lo:
        return lo
    if x > hi:
        return hi
    x
```

When passing a multi-statement lambda as a function argument, braces are required because indentation tracking is suppressed inside parentheses:

```
var result := apply(λx : int → int: {
    var a := x + 1;
    a * 2
}, 4)
```

#### Capture Rules

The lambda body has a restricted environment:

- **Built-in functions** (e.g., `assert`, `assert_eq`), **enum types**, and **module objects** (e.g., `std`) are always accessible without capture.
- **Non-replaceable user-defined functions** (the default) are always accessible without capture.  Since their binding is immutable, the lambda can safely reference them.
- **`@replaceable` functions** and **variables** must appear in the capture list to be used in the body.
- If no capture list is present (no `|…|` at all), the lambda cannot reference any capturable names from the enclosing scope.
- If a capture list is present but a referenced name is missing from it, a compile-time error is raised.

```
fn helper x : i32 → i32:
    x + 100

var offset := 10
var f := λx : i32 |offset| → i32: helper(x) + offset   // OK: helper is non-replaceable, offset is captured
var g := λx : i32 → i32: helper(x)                     // OK: helper needs no capture
var h := λx : i32 → i32: x + offset                     // ERROR: references 'offset' but has no capture list
```

#### Calling Lambdas

Lambdas are first-class values.  They can be assigned to variables, passed as arguments, and returned from functions.

```
var double := λx : int → int: x * 2
assert_eq(10, double(5))
```

Immediate application uses parentheses around the lambda:

```
var result := (λx : int → int: x + 1)(5)   // result is 6
```

#### Lambdas as Arguments and Return Values

```
fn apply f, x : i32 → i32:
    f(x)

fn make_adder n : i32:
    λx : int |n| → int: x + n

var add3 := make_adder(3)
assert_eq(8, add3(5))
assert_eq(15, apply(λx : int → int: x * 3, 5))
```

#### Function Currying

Calling a function with fewer arguments than its parameter list produces a partially-applied lambda.  The provided arguments are captured automatically.

```
fn add a : i32, b : i32 → i32:
    a + b

var add5 := add(5)                  // returns λb (partial add[5])
assert_eq(8, add5(3))
```

Multi-step currying is supported:

```
fn add3 a : i32, b : i32, c : i32 → i32:
    a + b + c

var f1 := add3(1)                   // λb, c
var f2 := f1(2)                     // λc
assert_eq(6, f2(3))               // 1 + 2 + 3
```

Lambdas themselves support partial application:

```
var mul := λx : int, y : int → int: x * y
var triple := mul(3)
assert_eq(15, triple(5))
```

#### The `@replaceable` Attribute

By default, functions are immutable bindings — once defined, their implementation cannot change.  Such functions are always accessible inside lambdas without being listed in the capture list, because the lambda's reference to the function can never become stale.

A function marked `@replaceable` can have its implementation swapped at runtime (see the language specification for function replacement).  Because its binding is mutable, a `@replaceable` function **must** be captured explicitly:

```
@replaceable
fn strategy x : i32 → i32:
    x * 2

// Must capture — strategy could change after the lambda is created
var f := λx : i32 |strategy| → i32: strategy(x)

// ERROR: strategy is @replaceable and not captured
var g := λx : i32 → i32: strategy(x)
```

This distinction ensures that lambdas with no capture list or an empty capture list are guaranteed to be pure with respect to user-defined state — they depend only on their parameters and immutable bindings.

#### Ignored Lambda Warning

A lambda value that is neither assigned to a variable nor returned produces a warning.  This catches accidental partial applications:

```
add(5)                             // WARNING: lambda value is not used
λx : int → int: x + 1             // WARNING: lambda value is not used
```

#### Design Rationale

| Feature | Haskell | Rust | Python | This language |
|---------|---------|------|--------|---------------|
| Lambda syntax | `\x -> x+1` | `\|x\| x+1` | `lambda x: x+1` | `λx : int → int: x+1` |
| Capture | implicit | explicit (`move`) | implicit | explicit (`\|…\|`) |
| Currying | automatic | no | no | automatic |
| Multi-expression body | no (one expr) | yes (block) | no (one expr) | yes (block or layout) |
| Unused lambda warning | no | yes (unused `Result`) | no | yes |

The explicit capture list follows the principle that a lambda's dependencies should be visible at the definition site.  Unlike Rust's closure inference, this language requires the programmer to declare what is captured — making the lambda self-documenting and preventing accidental capture of mutable state.

Automatic currying follows Haskell's model: every function of N parameters is conceptually a chain of N single-parameter functions.  This makes point-free style and function composition natural.


### Ranges as Values

Range expressions (`start…end` and `start…step…end`) are first-class values.  They can be stored in variables, passed as arguments, and iterated with `foreach`.

```
var r := 1…10
foreach i := r:
    ...
```

Ranges bind tighter than comparison but looser than arithmetic:

```
var r := 1 + 2 … 10 - 3             // equivalent to (1+2)…(10-3) = 3…7
```


### The `generate` Function

`generate` applies a function to each value in a range, collecting the results into an array.  It is the primary way to construct arrays from a mapping function.

#### Syntax

```
generate(func, range)
```

- **func**: any callable — a named function, a lambda, or a curried (partially-applied) function.
- **range**: a range value (`start…end` or `start…step…end`).
- **returns**: an array whose size equals the number of elements in the range.

#### Basic Usage

```
var squares := generate(λx : int → int: x * x, 1…5)
// squares = [1, 4, 9, 16, 25]

fn double x : i32 → i32:
    x * 2

var doubled := generate(double, 1…4)
// doubled = [2, 4, 6, 8]
```

#### With Currying

A curried function can be used as the mapping function:

```
fn multiply a : i32, b : i32 → i32:
    a * b

var tripled := generate(multiply(3), 1…5)
// tripled = [3, 6, 9, 12, 15]
```

#### With Stepped and Descending Ranges

```
var evens := generate(λx : int → int: x, 0…2…10)
// evens = [0, 2, 4, 6, 8, 10]

var desc := generate(λx : int → int: x * x, 3…1)
// desc = [9, 4, 1]
```

#### With Captures

```
var offset := 100
var arr := generate(λx : int |offset| → int: x + offset, 1…3)
// arr = [101, 102, 103]
```

#### Returning ∅ is Invalid

The mapping function must not return ∅.  This is a runtime error because the result array cannot contain empty optional values:

```
generate(λx : int → ∅: ∅, 1…5)    // ERROR: function must not return ∅
```

#### Compile-time Optimization (Future)

When the range bounds are compile-time constants, the compiler can determine the array size statically and allocate a fixed-size array.  When the bounds are runtime values, the result is a dynamically-sized array.  In the prototype interpreter, all arrays are dynamically sized.

For higher-rank results (matrices, tensors), `generate` will accept multi-dimensional ranges and return objects of matching rank.  This is planned for future implementation.

#### Design Rationale

| Feature | Haskell | Python | Rust | APL | This language |
|---------|---------|--------|------|-----|---------------|
| Map+collect | `map f [1..n]` | `[f(x) for x in range(1,n+1)]` | `(1..=n).map(f).collect()` | `f⍳n` | `generate(f, 1…n)` |
| Result type | list | list | `Vec<T>` | array | array |
| None/null in result | allowed | allowed | `Option` in vec | N/A | error |

`generate` combines mapping and collection into a single operation, emphasizing the functional construction of arrays.  The prohibition on ∅ return values ensures the result array is dense — every element contains a meaningful value.  This matches the array programming tradition (APL, J, BQN) where arrays are always rectangular and fully populated.


### The Reshape Operator (`⍴`)

The reshape operator `⍴` (APL rho) creates arrays and tensors by reshaping data to specified dimensions.  The left operand defines the shape; the right operand provides the data, which is cycled if it contains fewer elements than needed.

#### Syntax

```
shape ⍴ data
```

- **shape**: an integer (vector result) or a tuple of integers (matrix/tensor result).
- **data**: a scalar, array, or range whose elements fill the result.
- **returns**: a new array (or nested array for matrices/tensors) of the specified shape.

#### Vectors

When the left operand is a single integer, the result is a one-dimensional array:

```
var zeros := 64 ⍴ 0               // [0, 0, ..., 0] — 64 elements
var pattern := 5 ⍴ [1, 2, 3]      // [1, 2, 3, 1, 2] — cycling
var first3 := 3 ⍴ [10, 20, 30, 40, 50]  // [10, 20, 30] — truncating
```

The dimension can be a variable:

```
var n := 100
var buf := n ⍴ 0
```

When the right operand is a range, it is expanded before cycling:

```
var a := 5 ⍴ (1…3)                // [1, 2, 3, 1, 2]
```

#### Matrices and Tensors

When the left operand is a tuple, the result is a nested array whose depth matches the number of dimensions:

```
var m := (2, 3) ⍴ 0               // 2×3 matrix of zeros
var filled := (2, 3) ⍴ [1, 2, 3, 4, 5, 6]
// filled[0] = [1, 2, 3]
// filled[1] = [4, 5, 6]

var cycled := (3, 2) ⍴ [1, 2, 3, 4, 5]
// cycled[0] = [1, 2]
// cycled[1] = [3, 4]
// cycled[2] = [5, 1]  — cycling wraps around
```

Elements fill in row-major order, matching APL/BQN semantics.

#### Dimension Limit

The maximum number of dimensions is controlled by a global limit (`MAX_TENSOR_RANK`, default 8).  This same limit applies to all tensor operations in the language.  Exceeding it is a compile-time or runtime error:

```
var too_deep := (1,1,1,1,1,1,1,1,1) ⍴ 0   // error if more than MAX_TENSOR_RANK dims
```

#### Array Bounds Checking

Arrays perform strict bounds checking on both reads and writes.  Accessing an index outside `0..length-1` is a runtime error:

```
var a := [1, 2, 3]
var x := a[3]    // error: array index 3 out of range (length 3)
a[-1] ← 4      // error: array index -1 out of range (length 3)
```

This replaces the earlier behavior where out-of-bounds writes silently extended the array.  To grow an array, use `⍴` to reshape it to the desired size:

```
var W := 64 ⍴ generate(load_word, 0…15)   // extend 16-element result to 64
```

#### Operator Precedence

`⍴` binds tighter than arithmetic (`+`, `-`, `*`, `/`) but looser than unary operators (`-x`, `~x`).  This means:

```
3 * 4 ⍴ 0     // 3 * [0, 0, 0, 0] — reshape first, then multiply
2 + 3 ⍴ 5     // 2 + [5, 5, 5]    — reshape first, then add
```

#### Design Rationale

| Feature | APL/BQN | Python | Rust | This language |
|---------|---------|--------|------|---------------|
| Reshape | `n ⍴ data` | `numpy.reshape` | N/A | `n ⍴ data` |
| Fill mode | cycle | error on mismatch | N/A | cycle |
| Bounds check | implicit | `IndexError` | panic | `IndexError` |
| Syntax | glyph | method | method | glyph |

The APL tradition uses `⍴` both monadically (query shape) and dyadically (reshape).  This language currently implements only the dyadic form.  The monadic form (returning the shape of an array) may be added in future.

The cycling semantics follow APL: when the data has fewer elements than the result requires, elements are reused from the beginning.  This makes `n ⍴ scalar` a natural way to create filled arrays, and `n ⍴ array` extends arrays without requiring explicit concatenation.


### Array Concatenation (`⧺`)

The `⧺` operator (U+29FA, DOUBLE PLUS) concatenates two arrays at the outermost dimension.

#### Syntax

```
left ⧺ right
```

Both operands must be arrays.  The result is a new array whose elements are all elements of `left` followed by all elements of `right`.

#### Precedence

`⧺` binds tighter than `+` but looser than `⍴`:

```
a + b ⧺ c         // a + (b ⧺ c)
generate(f, r) ⧺ 48 ⍴ [0]   // generate(f, r) ⧺ (48 ⍴ [0])
```

This allows `⧺` and `⍴` to combine naturally without parentheses for common patterns like building a partially initialized array.

#### Semantics

- Both operands must be arrays; a non-array operand is a type error.
- The result preserves the element type of the left operand (falling back to the right if the left has no explicit type).
- Concatenation with an empty array is the identity: `a ⧺ (0 ⍴ [0])` yields `a`.
- `⧺` is left-associative: `a ⧺ b ⧺ c` is `(a ⧺ b) ⧺ c`.
- `⧺` is a line-continuation operator: an expression can break after it.

#### Example

```
// Build message schedule: 16 loaded words followed by 48 zero placeholders.
var W := generate(load_word, 0…15) ⧺ 48 ⍴ [0]
```

This is clearer than the equivalent `64 ⍴ generate(load_word, 0…15)` because it does not rely on the cycling semantics of `⍴` to silently repeat data that will be overwritten.

#### Comparison with Other Languages

| Language | Concatenation Syntax |
|----------|---------------------|
| APL      | `,` (catenate)      |
| BQN      | `∾` (join)          |
| Haskell  | `++`                |
| Python   | `+` (overloaded)    |
| Rust     | `.extend()` / `[a, b].concat()` |
| This language | `⧺`           |

Using a dedicated glyph avoids overloading `+` (which is element-wise addition on arrays) and is visually distinct from arithmetic.


### Fold Operators (`⌿` and `⍀`)

The fold operators are binary operators that reduce a container to a single value by repeatedly applying a function.  Two variants are provided:

- **Left fold** `⌿` (U+233F, APL FUNCTIONAL SYMBOL SLASH BAR): processes elements left-to-right.
- **Right fold** `⍀` (U+2340, APL FUNCTIONAL SYMBOL BACKSLASH BAR): processes elements right-to-left.

#### Syntax

```
func ⌿ container
func ⌿ (container, init)
func ⍀ container
func ⍀ (container, init)
```

- **func** (left operand): a binary function (named function, lambda, or any callable).
- **container** (right operand): an array or range to fold over.
- When the right operand is a 2-tuple literal `(container, init)`, the second element provides the initial accumulator value.
- When the right operand is not a 2-tuple literal, no initial value is provided: the leftmost element (for `⌿`) or rightmost element (for `⍀`) of the container is used as the initial accumulator.  In this case the container must not be empty.

#### Precedence

`⌿` and `⍀` bind at the same level as `⍴` (tighter than arithmetic, looser than unary).  The right operand is parsed at range-expression level, so `f ⌿ 1…5` works without parentheses.  Both are line-continuation operators.

#### Semantics

**With initial value** (2-tuple right operand):

Left fold processes all elements, starting from the initial value:

```
f ⌿ ([a, b, c], init) = f(f(f(init, a), b), c)
```

Right fold processes all elements in reverse, starting from the initial value:

```
f ⍀ ([a, b, c], init) = f(a, f(b, f(c, init)))
```

When the container is empty, both folds return the initial value unchanged.

**Without initial value** (bare container):

Left fold uses the first element as the accumulator and folds over the remaining elements:

```
f ⌿ [a, b, c] = f(f(a, b), c)
```

Right fold uses the last element as the accumulator and folds over the remaining elements in reverse:

```
f ⍀ [a, b, c] = f(a, f(b, c))
```

Folding an empty container without an initial value is a runtime error.  A single-element container returns that element unchanged.

#### Examples

Summation without initial value:

```
var total := (λa : int, b : int → int: a + b) ⌿ [1, 2, 3, 4, 5]
// total = 15
```

Summation with explicit initial value:

```
var total := (λa : int, b : int → int: a + b) ⌿ ([1, 2, 3, 4, 5], 100)
// total = 115
```

Bit packing (used in SHA-256 to assemble the final hash from eight 32-bit words).  The initial value 0 is needed because the first hash word must be shifted into position:

```
var hash := (λacc : int, h : int → int: (acc « 32) | h) ⌿ (H, 0)
```

String concatenation without initial value:

```
var joined := (λacc : str, s : str → str: acc + s) ⌿ ["a", "b", "c"]
// joined = "abc"
```

Folding over a range:

```
var sum := (λa : int, b : int → int: a + b) ⌿ 1…100
```

Named functions as the left operand:

```
fn add x : int, y : int → int:
    x + y

var total := add ⌿ [10, 20, 30]   // 60
```

Currying and fold combine naturally.  A curried function produces the mapping, and fold reduces the result:

```
fn multiply a : int, b : int → int:
    a * b

var triple := multiply(3)
var tripled := generate(triple, 1…5)   // [3, 6, 9, 12, 15]
var total := add ⌿ tripled             // 45
```

#### Design Rationale

| Feature | APL/BQN | Haskell | Rust | Python | This language |
|---------|---------|---------|------|--------|---------------|
| Left fold | `/` (reduce) | `foldl`/`foldl1` | `.fold()` | `functools.reduce` | `f ⌿ x` |
| Right fold | N/A | `foldr`/`foldr1` | `.rfold()` | N/A | `f ⍀ x` |
| Init value | optional | required/optional | required | optional | optional |
| Syntax | operator modifier | function | method | function | binary operator |

The glyph choice follows the APL tradition of using `/` and `\` with bar modifiers.  Using binary operator syntax (`func ⌿ container`) rather than function-call syntax aligns fold with other array operators in the language (`⍴`, `⧺`) and reads naturally: the function is on the left, the data on the right.

The initial value is optional.  When omitted, the first or last element of the container serves as the accumulator, matching the behavior of APL's reduce and Haskell's `foldl1`/`foldr1`.  When an initial value is needed (e.g., when the accumulator type differs from the element type, or when the container may be empty), a 2-tuple literal `(container, init)` on the right side provides it.  This avoids a separate operator or function for the two cases.

Both folds accept arrays and ranges as containers.  Using a non-iterable value (such as a scalar integer) is a type error.


### The `catch` Statement

The `catch` statement provides scoped error handling at the syntactic level.  Unlike exception systems in C++ or Java, `catch` blocks do **not** intercept errors from called functions.  Only errors that originate from operations directly written inside the `catch` block are caught.

#### Syntax

```
fn safe_access arr : i32[], idx : i32 → i32?:
    catch:
        arr[idx]
```

The `catch` keyword is followed by a block (using `:` with indentation or `{ }`), following the same rules as `if`, `while`, and `foreach`.  The enclosing function must have an optional (`T?`) or expected (`T!`, i.e., `T?std.errors`) return type.

#### Semantics

When an operation inside the `catch` block raises a runtime error (such as an out-of-bounds array access, integer overflow, or type error):

1. The error does **not** terminate the program.
2. The error is converted to the appropriate return value:
   - For **optional** return types (`T?`): the function returns `∅`.
   - For **expected** return types (`T!`): the function returns `err(e)` where `e` is the corresponding `std.errors` enum value.
3. Execution resumes at the function's caller.

If no error occurs, the block's result value is used normally as the function's return value (wrapped in `some()` or `ok()` as appropriate).

#### Error Mapping

Runtime errors are mapped to `std.errors` enum values:

| Python Exception  | `std.errors` Value    |
|-------------------|-----------------------|
| `IndexError`      | `index_out_of_range`  |
| `OverflowError`   | `integer_overflow`    |
| `TypeError`       | `type_mismatch`       |

If no matching enum value is found, a string description of the error is used as the error value.

#### Syntactic Scope Only

The critical design property of `catch` is **syntactic scope**.  Errors from function calls inside the `catch` block are **not** caught:

```
fn risky → i32:
    var a := [1]
    a[99]              // raises IndexError

fn caller → i32?:
    catch:
        risky()        // error from risky() propagates — NOT caught
        var a := [1, 2]
        a[5]           // this error WOULD be caught (direct operation)
```

This means:
- `a[5]` inside the `catch` block is a direct operation.  Its `IndexError` is caught and converted to `∅`.
- `risky()` is a function call.  Errors from inside `risky` propagate normally, as if the `catch` block were not present.

This design avoids the problems of stack-unwinding exception systems: reasoning about control flow remains local, and functions cannot silently swallow errors from their callees.

#### Comparison with Other Languages

| Feature | C++ `try/catch` | Rust `?` | Zig `catch` | This language |
|---------|-----------------|----------|-------------|---------------|
| Scope | Stack-unwinding | Expression-level | Expression-level | Syntactic block |
| Cross-call | Catches all | Propagates | Propagates | Does not catch |
| Error type | Exception classes | `Result<T,E>` | `anyerror` | `std.errors` enum |
| Syntax | Block with type | Postfix operator | Binary operator | Block statement |

The `catch` statement is complementary to the `?` postfix operator: `?` propagates errors from expected values, while `catch` converts direct runtime errors into return values.


### Built-in Test System

Unit testing is built into the language, similar to Rust's `#[test]` attribute.  Functions are annotated with `@test` to mark them as test functions.  The annotation accepts an optional list of function names that the test covers.

#### Annotation Syntax

```
@test
fn test_something → ∅:
    ...

@test(sha256)
fn test_sha256_abc → ∅:
    ...

@test(encrypt, decrypt)
fn test_round_trip → ∅:
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

#### Compile-Time Assertions

Two compile-time assertion functions verify conditions using only constant expressions.  If any argument is not a compile-time constant (i.e., it references a variable), a compilation error is raised immediately:

- `static_assert(condition)` — fails at compile time if the condition is `false` or zero.  An optional second argument provides a custom error message: `static_assert(2 + 2 == 4)`, `static_assert(false, "unreachable")`.

- `static_assert_eq(expected, actual)` — fails at compile time if the two constant values differ: `static_assert_eq(120, 2 * 3 * 4 * 5)`.

Constant expressions include literals, arithmetic/logic operations on literals, unary operators, and array/tuple literals composed of constants.  References to variables — even `const` variables — are not compile-time constants for these purposes; use `assert` or `assert_eq` for those.

```
static_assert(true)                     /* OK */
static_assert_eq(10, 3 + 7)            /* OK */
static_assert_eq("hello", "hello")     /* OK */

var x := 42
static_assert(x)                       /* ERROR: not a compile-time constant */
```

| Feature | C/C++ | Rust | Zig | This language |
|---------|-------|------|-----|---------------|
| Compile-time assert | `static_assert` | `const_assert!` (nightly) | `comptime` + assert | `static_assert` / `static_assert_eq` |

#### Type Introspection

Two built-in functions return reified type values that can be compared for equality:

- `@typeof(expr)` — evaluates the expression and returns a `type` value representing its runtime type.  The type name reflects the concrete type: `int`, `i32`, `u8`, `str`, `bool`, `\N{EMPTY SET}`, `array`, `tuple`, `fn`, `\N{GREEK SMALL LETTER LAMDA}`, or an enum name.

- `@resultof(func)` — looks up a named function and returns a `type` value for its declared return type.

Type values can be compared with `==` and used with `assert_eq` and `static_assert_eq`:

```
var x : i32 = 10
assert_eq(@typeof(x), @typeof(x + 1))         /* both are i32 */

fn example → i32: 42
assert_eq(@resultof(example), @typeof(x))      /* i32 == i32 */

/* With static_assert_eq for compile-time checks */
static_assert_eq(@typeof(42), @typeof(1 + 2))  /* both are int */
static_assert_eq(@typeof("a"), @typeof("b"))   /* both are str */
```

| Feature | C++ | Rust | Zig | This language |
|---------|-----|------|-----|---------------|
| Type-of expression | `decltype(expr)` | — | `@TypeOf` | `@typeof(expr)` |
| Return type query | `decltype(f())` | — | `@typeInfo` | `@resultof(func)` |
| Type equality | `std::is_same_v` | `TypeId` | `==` | `==` |

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
fn test_sha256_empty → ∅:
    var data := std.bytes("")
    var hash := sha256(data)
    assert_eq(hash, 0xe3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855)

@test(sha256)
fn test_sha256_abc → ∅:
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

### Expected Diagnostic Testing (`@expect`)

The `@expect` annotation allows writing tests that verify the interpreter/compiler produces specific error or warning messages.  This is essential for testing that the language's static and dynamic checks actually reject invalid programs and produce the correct diagnostics.

`@expect` can be applied at two levels: **function-level** (before a function definition) and **statement-level** (before an individual statement inside a function body).

#### Function-Level Syntax

```
@expect error "regex pattern"
@expect warning "regex pattern"
fn function_name → ∅:
    /* code that should trigger the diagnostic */
```

Multiple `@expect` annotations can appear before a single function.  The level keyword (`error` or `warning`) specifies what kind of diagnostic is expected, and the string is a regular expression matched against the actual diagnostic message.

#### Statement-Level Syntax

```
fn test_something → ∅:
    @expect warning "redefinition of foreach variable"
    var i := 99
```

Statement-level `@expect` wraps a single statement.  The evaluator executes the statement, captures any errors and warnings it produces, and matches them against the expectations.  If all expectations are satisfied, execution continues normally.  If any expectation is unmatched, the test fails.

This form is especially useful for testing warnings, since warnings do not terminate execution and the function can verify the behavior that follows the warning.

#### Semantics

**Function-level:**

1. The interpreter attempts to parse and evaluate the annotated function body.
2. Any error produced during parsing or evaluation is captured rather than terminating the interpreter.
3. Each captured diagnostic is matched against the `@expect` annotations in order.  An annotation is satisfied when its level matches and its regex pattern matches (via `re.search`) the diagnostic message.
4. If all `@expect` annotations are satisfied, the function is silently accepted — the test passes.
5. If any `@expect` annotations remain unmatched, the test fails with a diagnostic showing both the unmatched expectations and the actual diagnostics produced.
6. If no diagnostic is produced but one was expected, the test fails with "expected diagnostics not produced".

Since the interpreter stops at the first error in a function body, each `@expect error` function typically tests exactly one error condition.

**Statement-level:**

1. The evaluator executes the annotated statement, capturing any raised exceptions as errors and any warnings emitted during execution.
2. The captured diagnostics are matched against the expectations using the same regex-matching rules as function-level `@expect`.
3. If all expectations match, execution continues with the next statement.
4. If any expectation remains unmatched, a `TypeError` is raised (which the enclosing `@test` function will report as a test failure).

#### Error Recovery

When an `@expect`-annotated function has a parse error, the parser recovers by skipping tokens until the next top-level definition.  The parse error message is captured and matched against the expectations.  This allows testing for syntax errors without aborting the entire file.

#### Examples

Function-level `@expect` for errors:

```
@expect error "cannot assign to const variable 'x'"
fn error_const_assign → ∅:
    const x := 42
    x ← 99

@expect error "unexpected token: 'fn'"
fn error_nested_fn → ∅:
    fn inner → ∅:
        std.print("bad")
```

Statement-level `@expect` for warnings inside a `@test` function:

```
@test
fn warn_foreach_redef → ∅:
    var total := 0
    foreach i := 1…3:
        @expect warning "redefinition of foreach variable 'i'"
        var i := 99
        total ← total + i
    assert_eq(total, 297)
```

This test verifies both that the warning is produced and that the redefined variable takes effect (each iteration uses 99, so the total is 297).

#### Integration with Test Modes

`@expect` tests are processed in both `--test` and normal mode:

- In `--test` mode, each function-level `@expect` function is reported like a regular test (`ok` / `FAILED`) and included in the test summary counts.  Statement-level `@expect` operates within the enclosing `@test` function.
- In normal mode, function-level `@expect` tests are verified silently on success.  If any `@expect` test fails, the program terminates with exit code 1 before running the `@start` function.
- The `--skip-tests` flag does **not** suppress function-level `@expect` verification — these are compile-time checks, not runtime tests.

#### Design Rationale

| Feature | Rust | LLVM FileCheck | This language |
|---------|------|----------------|---------------|
| Error testing | `#[should_panic]` | `// expected-error` | `@expect error "pattern"` |
| Warning testing | No | `// expected-warning` | `@expect warning "pattern"` |
| Pattern matching | No (message ignored) | Fixed substring | Regex |
| Parse error testing | No (compile error = test infra error) | Yes | Yes (parser recovers) |
| Statement granularity | No | Yes (line-based) | Yes (`@expect` on statements) |
| Integrated with test runner | Yes | Separate tool | Yes |

The `@expect` annotation fills a gap that most languages handle with external test harnesses.  By integrating diagnostic-expectation testing into the language's test system, the entire test suite — positive tests (`@test`) and negative tests (`@expect`) — can live in the same source files and run with the same `--test` invocation.  The statement-level form is particularly powerful: it allows testing warnings and non-fatal diagnostics within otherwise-normal test functions, verifying both the diagnostic and the runtime behavior that follows.


### Enumeration Types

Enumerations define a named set of integer constants grouped under a single type.  Enum members are not in the global namespace — they must be qualified with the enum's name (e.g., `Color.red`).

#### Syntax

```
enum Name [: underlying_type]:
    member1 [= value]
    member2 [= value]
    ...
```

The `enum` keyword introduces the definition.  An optional underlying type (e.g., `u8`, `u16`, `u32`) controls the storage width.  Each member is an identifier optionally followed by `= integer_value`.

#### Auto-Numbering

Members without explicit values are auto-numbered sequentially starting from 0 (or from the value after the previous explicitly-set member):

```
enum Color:
    red         /* 0 */
    green       /* 1 */
    blue        /* 2 */

enum Level:
    low         /* 0 */
    medium      /* 1 */
    high = 10   /* 10 */
    critical    /* 11 */
```

#### Member Access

Enum members are accessed through the enum's name, not as bare identifiers:

```
var c := Color.red
var l := Level.high
```

#### Comparison

Enum values of the same type can be compared with `==` and `!=`.  Comparing values from different enum types is a type error.  Enum values can also be compared with integer literals:

```
var c := Color.red
assert_eq(c == Color.red, true)     /* same-type comparison */
assert_eq(c == 0, true)             /* compare with integer */
```

```
/* ERROR: cannot compare enum 'Color' with enum 'Status' */
var x := Color.red == Status.ok
```

#### Underlying Type

The optional underlying type controls the integer width used to store enum values:

```
enum SmallEnum : u8:
    a
    b
    c
```

When no underlying type is specified, the default is `int` (arbitrary precision).

#### Flag Enums (`@flag`)

The `@flag` attribute changes auto-numbering to powers of two, making the enum suitable for bitwise flag combination:

```
@flag
enum Perms:
    read        /* 1 */
    write       /* 2 */
    exec        /* 4 */
```

If no member has the value 0, a `nil` member is automatically added:

```
Perms.nil       /* 0 — auto-generated */
Perms.read      /* 1 */
Perms.write     /* 2 */
Perms.exec      /* 4 */
```

If a member explicitly defines the value 0, no `nil` is generated:

```
@flag
enum Mode:
    off = 0     /* explicit zero — no auto nil */
    read = 1
    write = 2
```

#### Flag Operations

Flag enums support bitwise operations to combine, test, and remove flags:

| Operation | Syntax | Result |
|-----------|--------|--------|
| Combine | `a \| b` | union of flags |
| Intersect | `a & b` | intersection of flags |
| Toggle | `a ^ b` | symmetric difference |
| Complement | `~a` | all defined flags except those in `a` |

These operations are only valid on `@flag` enums.  Attempting bitwise operations on a non-flag enum is a type error.  Cross-enum operations (mixing two different enum types) are also type errors.

```
var rw := Perms.read | Perms.write    /* combine: 3 */
var r := rw & Perms.read              /* intersect: Perms.read */
var toggled := rw ^ Perms.write       /* toggle: Perms.read */
var others := ~rw                     /* complement: Perms.exec */

/* Test membership */
var has_read := (rw & Perms.read) == Perms.read    /* true */
var has_exec := (rw & Perms.exec) == Perms.exec    /* false */
```

The complement operator `~` masks against the union of all defined member values, so `~Perms.read` yields `Perms.write | Perms.exec` rather than a full integer complement.

#### The `std.errors` Enum

A built-in enum `std.errors` provides standardized error codes grouped by category:

| Range | Category | Members |
|-------|----------|---------|
| 100-199 | Runtime errors | `division_by_zero` (100), `index_out_of_range` (101), `stack_overflow` (102), `null_dereference` (103), `integer_overflow` (104), `assertion_failed` (105) |
| 200-299 | Compile-time errors | `type_mismatch` (200), `unknown_type` (201), `syntax_error` (202), `undefined_variable` (203), `arity_mismatch` (204) |
| 300-399 | Library/runtime errors | `file_not_found` (300), `permission_denied` (301), `io_error` (302), `allocation_failed` (303), `invalid_argument` (304) |

```
var err := std.errors.division_by_zero
assert_eq(err == 100, true)
```

The grouping by integer ranges allows category checks:  runtime errors are in 100-199, compile-time errors in 200-299, library errors in 300-399.

#### Design Rationale

| Feature | C/C++ | Rust | Zig | This language |
|---------|-------|------|-----|---------------|
| Scoping | global (C), scoped (`enum class`, C++) | scoped | scoped | scoped (qualified access) |
| Underlying type | optional (`enum class : u8`) | implicit | `u8`..`u64` | optional (`: u8`) |
| Flag support | manual | `bitflags!` crate | manual | `@flag` attribute |
| Auto nil | N/A | N/A | N/A | auto-generated for `@flag` |
| Bitwise ops on flags | manual | `bitflags!` | manual | built-in (`\|`, `&`, `^`, `~`) |
| Cross-type comparison | allowed | error | error | error |

The `@flag` attribute eliminates the boilerplate of manually assigning powers of two and defining bitwise operations.  The automatic `nil` member for zero-valued flag sets prevents the common bug of forgetting to define an "empty" state.  Scoped access prevents name collisions between members of different enums.
