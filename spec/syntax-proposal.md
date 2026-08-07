Language Syntax Proposal (Draft)
=================================

This document proposes the concrete syntax for the language, as implemented in
the Python-based prototype interpreter at `interp/`. The syntax is still evolving;
these are initial choices to be validated through experiments.


1. File Structure
-----------------

Source files have the extension `.nl` (NGPL). A source file contains a sequence
of top-level definitions: function definitions and variable definitions. No code
may appear outside these constructs.

A single function in a compilation unit may be designated as the **startup function**
using the `@start` attribute before its definition.


2. Comments
-----------

Line comments start with `//` and extend to the end of the line.

Block comments are delimited by `/*` and `*/`. They may span multiple lines.


3. Identifiers and Keywords
----------------------------

Identifiers consist of ASCII letters, digits, underscores, and the Unicode symbols
`→`, `′`, `` ` ``. An identifier must not begin with a digit.

Keywords are reserved words that cannot be used as identifiers:

    fn  var  if  else  elif  while  opt  is  none  true  false  let  import  match


4. Integer Literals
-------------------

Integers are written in decimal by default. Binary (prefix `0b` or `₀ᵦ`) and
hexadecimal (prefix `0x` or `₀ₓ`) literals are also supported. The type suffix
indicates the bit width:

    42          — i64 (default signed 64-bit)
    42u8        — u8  (unsigned 8-bit)
    42i16       — i16 (signed 16-bit)
    0xFF_u32    — u32 (unsigned 32-bit)

Valid signed widths: i1, i8, i16, i32, i64.
Valid unsigned widths: u8, u16, u32, u64 (u1 is not meaningful without sign).

The default width is **i64** (signed 64-bit). The maximum signed width is **i63**,
and the maximum unsigned width is **u64**.


5. String Literals
------------------

Simple strings are delimited by double quotes (`"…"`). Escape sequences:

    \n   newline
    \t   tab
    \\   backslash
    \"   double quote
    \u{NNNN}  Unicode code point (hex)

Strings cannot span multiple lines.


6. Boolean Literals
-------------------

Two literals: `true` and `false`. Boolean values are distinct from integers
(implicit conversion is a compile error in strict mode).


7. Optional Type
----------------

The optional type is written `opt[T]` where `T` is the element type, or simply
`opt` which defaults to `opt[none]`. The two optional values are:

    none          — the empty optional
    some(value)   — an optional containing a value


8. Variable Definitions
------------------------

    var name = expression
    var name: Type = expression

The `var` keyword introduces a new variable with an initial value. The type is
optional; when omitted it is inferred from the initializer.

There is **no** separate assignment operator at this stage (the `←` operator
from the requirements is planned for a future version). Currently, variables
are immutable after definition (like `let` in Rust), and mutation will require
a separate mechanism.


9. Function Definitions
------------------------

    fn name(params) -> ReturnType { body }

Function definitions consist of:

- The `fn` keyword
- The function name
- A parenthesized, comma-separated parameter list. Each parameter is a `name: Type`.
  Parameters may omit their type (defaulting to inference).
- An optional `-> ReturnType` clause (required if the body might cause ambiguity).
- A brace-delimited body containing statements.

Parameters are passed by value (for integers and strings). No references or
pointers at this stage.


10. Function Calls
------------------

Function calls use parentheses:

    name(arg1, arg2)
    fs.cwd()
    hash.format(None, stdout)

If a function takes no arguments, empty parentheses are required: `f()` is not
the same as referring to the function value (future currying support).


11. Expressions
---------------

Supported expression forms:

- Integer and string literals
- Variable references
- Function calls
- Arithmetic: `+`, `-`, `*`, `/` (integer division truncates toward zero)
- Comparison: `==`, `!=`, `<`, `>`, `<=`, `>=`
- Boolean logic: `and`, `or`, `not`
- Concatenation: strings use `+`
- Optional construction: `some(value)`, `none`


12. Statements
--------------

### Expression Statement
Any expression followed by nothing is a statement (useful for function calls with
side effects, like file I/O).

### Variable Definition
    var name = expr          or          var name: Type = expr

### If Statement
    if condition { body }
    if condition { body } else { alternate }
    if c1 { b1 } elif c2 { b2 } else { b3 }

The `else` branch is optional. When omitted and the condition evaluates to `false`,
execution continues after the if-statement.

### While Loop
    while condition { body }

The loop body repeats as long as the condition evaluates to `true`. There is no
explicit `break` or `continue` at this stage.


13. Return Statement
--------------------

Functions return from their enclosing scope:

    return expr

If no return value is needed, `return` alone returns `none`. If a function has no
explicit return and no declared return type, it implicitly returns `none`.


14. Attribute Syntax (for future)
---------------------------------

Planned attribute syntax for designating startup functions and other purposes:

    @start                — mark this function as the program entry point
    @comptime             — compile-time evaluation
    @test                 — unit test function

Attributes precede the definition they annotate, on their own line.


15. Design Decisions to Validate
---------------------------------

### 15a. Function Call Delimiters

The proposal uses `(...)` for function calls. CLAUDE.md raises the question of
whether `[...]` or no delimiters (Haskell-style) might be better. The current
prototype uses `(...)` because:

- It is immediately familiar to programmers from C/C++, Python, Rust, etc.
- It leaves Unicode square brackets available for indexing (`arr[0]`).
- Parentheses and square brackets are visually distinct in source code reviews.

**Question:** Should function calls use `[...]`, `(...)`, or no delimiters?

### 15b. Operator Precedence

The current prototype uses standard C-like precedence:

    1. `*` `/` (highest)
    2. `+` `-`
    3. `<` `>` `<=` `>=`
    4. `==` `!=`
    5. `and`
    6. `or` (lowest)

CLAUDE.md raises the question of whether to adopt no-precedence (APL-style,
right-to-left or left-to-right). The current prototype uses precedence because:

- Mathematical expressions remain readable without excessive parentheses.
- It matches most programmers' expectations.
- No-precedence can be achieved via macros in a future version.

**Question:** Should operator precedence be kept, removed entirely, or use a
hybrid approach (precedence for arithmetic only)?

### 15c. Immutability Default

Variables defined with `var` are currently immutable. Mutation would require
a separate mechanism (e.g., `mut var name = expr`). CLAUDE.md asks to determine
when explicit lifetime control is necessary. The current prototype treats all
variables as immutable by default, matching functional programming conventions.

**Question:** Should `var` introduce mutable or immutable bindings? What keyword
would you prefer for the opposite case?


16. Example Program
-------------------

The following program demonstrates the proposed syntax:

    /* Hash and display CLAUDE.md */
    @start
    fn main() -> none {
        var dir = fs.cwd();
        var file = dir.openFile("CLAUDE.md");
        var data = file.read_file(heap.allocator());
        var hash = sha256(data);
        hash.format(None, get_stdout());
        " CLAUDE.md\n".format(None, get_stdout());
    }

This program:
1. Opens the current directory (getting a `dirfd`)
2. Opens `CLAUDE.md` relative to that directory
3. Reads its entire content into allocated memory
4. Computes the SHA-256 hash as an arbitrary-length integer
5. Prints the hash in hexadecimal, followed by two spaces, the filename, and newline

