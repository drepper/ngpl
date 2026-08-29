# tree-sitter-ngpl

A [tree-sitter](https://tree-sitter.github.io) grammar for NGPL.

    tree-sitter generate
    tree-sitter test
    tree-sitter parse ../src/check.ngpl

## What the scanner is for

NGPL lays its blocks out by indentation, so the newline that ends a
statement and the indent that opens a block are handed over by the
external scanner in `src/scanner.c` rather than matched by a pattern.
Two things put them away again, and both fall out of what the parser can
accept where it stands:

- a line inside `(`, `[`, `{` or `⸨`, where the grammar has no place for
  a newline, so the scanner is not asked for one;
- a line whose last token is an operator still waiting for its
  right-hand side, which is the same thing for the same reason.

That is the rule the compiler's own lexer keeps by counting brackets and
its interpreter by looking back at the last token on the line, arrived
at here without either count.

The scanner also reads string literals, because the multi-line form ends
at the first three quotes and holds single ones freely, which is easier
to say as a loop than as a regular expression.

## What it was checked against

Every NGPL source in the repository is parsed and the tree examined for
`ERROR` and `MISSING` nodes:

| corpus | files | clean |
| --- | --- | --- |
| the compiler's own source, `src/` | 35 | 35 |
| the compiled-subset tests, `tests/compile/` | 85 | 85 |
| the full-language tests, `tests/` | 116 | 112 |

The four that are not clean use the corners of the full language that
this grammar does not reach yet: a macro's rewrite rules written
`⟪…⟫ → ⟪…⟫`, an if used as a value whose branches are written in braces,
and one file that ends with a function header and no body.

`test/corpus` holds the shapes worth pinning: the definitions, the
statements, the binding powers, the layout, and both forms of string.

## The binding powers

They are the compiler's own, from `bin_bp()` in `src/parse.ngpl`,
doubled so that the quantifiers `∀ ∃ ∄` can sit between the comparisons
and the range, which is where the compiler puts them: a comparison ends
a quantifier, and a range is inside one.
