"""Recursive descent parser for the NGPL language.

Builds an Abstract Syntax Tree (AST) from a token stream produced by the lexer.
Supports function definitions, variable definitions, if/while/control flow,
expressions with operator precedence, and function/method calls.

Blocks can use brace-delimited { ... } or layout-driven scoping with : and
indentation (INDENT/DEDENT tokens).
"""

from interp.ast import (
    IntLit, FloatLit, StrLit, CharLit, BoolLit, NoneLit, VarRef, RefExpr, BorrowExpr,
    BinOp, UnaryOp,
    IfStmt, WhileStmt, ReturnStmt, FuncDef, VarDef, DestructureDef, ExprStmt,
    FuncCall, MethodCall, OptSome, GetAttr,
    ArrayLit, Subscript, SliceAccess, MultiSlice, ArrayAlloc, TryUnwrap,
    DropUnitExpr,
    LimitExpr,
    RangeExpr, ForEachStmt, ExpectStmt, WrapExpr, TypeDef, EnumDef,
    LambdaExpr, ReshapeExpr, TupleLit, CatchStmt, EnumerateExpr,
    StaticAssert, StaticAssertEq, TypeOfExpr, ResultOfExpr, SizeOfExpr, FoldExpr,
    OperatorRef,
    UnitExpr, UnitDef, UnitName, UnitBinOp, UnitSqrt, UnitLit, SumTypeDef,
    UnitOfExpr, UnitRefExpr,
    StructDef, ImplBlock, StructLit,
    MatchStmt, MatchArm, ExpErr,
    set_pos,
)
from interp.lexer import Token, KEYWORDS


# Token types that can begin a top-level definition, either as the
# definition keyword itself or as an annotation preceding it.
DEFINITION_STARTERS = frozenset({
    "START", "REPLACEABLE", "TEST", "FLAG", "IMPURE", "EXPECT", "REPR",
    "HOT", "COLD", "LISTABLE",
    "ENUM", "STRUCT", "IMPL", "UNIT", "TYPE", "FN", "LET",
})


class ParseError(Exception):
    """Raised when the parser encounters invalid input."""

    def __init__(self, message, token=None):
        self.raw_message = message
        self.token = token
        if token:
            self.line = token.line
            self.col = token.col
            self.end_col = token.end_col
            msg = f"Line {token.line}, col {token.col}: {message}"
        else:
            self.line = 0
            self.col = 0
            self.end_col = None
            msg = message
        super().__init__(msg)


_TYPE_TO_KEYWORD: dict[str, str] = {v: k for k, v in KEYWORDS.items()}


# The operators of each precedence level.  A saturating operator sits
# with the exact one it answers to, so the two group alike.
_ADD_OPS = frozenset({"+", "-",
                      "\N{SQUARED PLUS}", "\N{SQUARED MINUS}"})
_MUL_OPS = frozenset({"\N{MULTIPLICATION SIGN}", "\N{DIVISION SIGN}", "%",
                      "\N{SQUARED TIMES}"})
_MINMAX_OPS = frozenset({"\N{LEFT CEILING}", "\N{LEFT FLOOR}"})

# What a program written before the comparison operators took their own
# glyphs reaches for.  Named rather than left to fall out as a parse
# error, every such program using them.
_OLD_CMP_SPELLINGS = {
    "==": "equality is written '='",
    "!=": "inequality is written '\N{NOT EQUAL TO}'",
}
# The same glyphs in front of an operand, where they are the case of
# text rather than the larger or smaller of two numbers.
_CASE_OPS = _MINMAX_OPS
# What binds at that level: the two above, finding a position, and
# asking whether something is there at all.
_PICK_OPS = _MINMAX_OPS | {"\N{APL FUNCTIONAL SYMBOL IOTA}",
                           "\N{SMALL ELEMENT OF}"}

# The fold operators, and the operators that may be folded with.
_FOLD_OPS = frozenset({"\N{APL FUNCTIONAL SYMBOL SLASH BAR}",
                       "\N{APL FUNCTIONAL SYMBOL BACKSLASH BAR}"})
_FOLDABLE_OPS = frozenset({
    "+", "-", "\N{MULTIPLICATION SIGN}", "\N{DIVISION SIGN}", "%",
    "\N{SQUARED PLUS}", "\N{SQUARED MINUS}", "\N{SQUARED TIMES}",
    "\N{LEFT CEILING}", "\N{LEFT FLOOR}",
    "\N{DOUBLE PLUS}", "\N{UPWARDS ARROW}",
    "&", "|", "^", "<<", ">>", "\N{LEFT-POINTING DOUBLE ANGLE QUOTATION MARK}",
    "\N{RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK}",
    "\N{ANTICLOCKWISE OPEN CIRCLE ARROW}", "\N{CLOCKWISE OPEN CIRCLE ARROW}",
    "\N{LOGICAL AND}", "\N{LOGICAL OR}", "\N{CIRCLED PLUS}",
    "\N{NAND}", "\N{NOR}",
})


def _as_names(names):
    """The names a destructuring binds, as something hashable.

    A parameter's name slot is looked up in sets and dictionaries, so
    the names a destructured one holds are kept in tuples rather than
    lists.
    """
    return tuple(_as_names(n) if isinstance(n, list) else n for n in names)


class Parser:
    """Recursive descent parser."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def _set_pos(self, node, tok):
        """Attach source position from a token to an AST node."""
        return set_pos(node, tok.line, tok.col, tok.end_col)

    def _set_binop_pos(self, node, left, right, op_tok):
        """Attach position spanning from left operand through right operand."""
        left_pos = getattr(left, "pos", None)
        right_pos = getattr(right, "pos", None)
        if left_pos is not None and right_pos is not None and left_pos[0] == right_pos[0]:
            return set_pos(node, left_pos[0], left_pos[1], right_pos[2])
        return self._set_pos(node, op_tok)

    # ------------------------------------------------------------------
    # Token access helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tok_display(tok: Token) -> str:
        """Format a token for user-facing error messages."""
        kw = _TYPE_TO_KEYWORD.get(tok.type)
        if kw is not None:
            return f"'{kw}'"
        if tok.type == "IDENT":
            return f"identifier '{tok.value}'"
        if tok.type == "INT":
            return f"integer {tok.value}"
        if tok.type == "CHAR":
            return f"character '{chr(tok.value)}'"
        if tok.type == "STR":
            return f"string \"{tok.value}\""
        if tok.type in ("PUNCT", "OP"):
            return f"'{tok.value}'"
        if tok.type == "EOF":
            return "end of file"
        if tok.type == "NEWLINE":
            return "newline"
        if tok.type == "INDENT":
            return "indent"
        if tok.type == "DEDENT":
            return "dedent"
        return f"'{tok.value}'"

    @staticmethod
    def _type_display(type_: str, value: str | None = None) -> str:
        """Format an expected token type for user-facing error messages."""
        if value is not None:
            return f"'{value}'"
        kw = _TYPE_TO_KEYWORD.get(type_)
        if kw is not None:
            return f"'{kw}'"
        label = {
            "IDENT": "identifier", "INT": "integer", "STR": "string",
            "PUNCT": "punctuation", "OP": "operator", "EOF": "end of file",
            "NEWLINE": "newline",
        }.get(type_)
        if label is not None:
            return label
        return type_.lower()

    def _cur(self):
        """Return the current token without consuming it."""
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return self.tokens[-1]  # EOF

    def _eat(self, type_, value=None):
        """Consume and return the current token if it matches; else error."""
        tok = self._cur()
        if tok.type != type_:
            raise ParseError(
                f"expected {self._type_display(type_, value)}, "
                f"got {self._tok_display(tok)}", tok)
        if value is not None and tok.value != value:
            raise ParseError(f"expected '{value}', got {self._tok_display(tok)}", tok)
        self.pos += 1
        return tok

    def _try_eat(self, type_, value=None):
        """Consume and return the current token if it matches; otherwise return None."""
        tok = self._cur()
        if tok.type == type_ and (value is None or tok.value == value):
            self.pos += 1
            return tok
        return None

    def _check(self, *types):
        """Return True if the current token type is one of the given types."""
        return self._cur().type in types

    def _parse_array_suffix(self) -> str:
        """Parse the bracketed dimensions of an array type.

        One entry per dimension, each either a size or empty, so that
        `[4]`, `[]`, `[2,3]`, and `[2,]` all read the same way: a size
        fixes that dimension, an empty entry leaves it open.

        Returns the text to append to the element type, or "" when the
        next token does not open an array type.
        """
        if not (self._check("PUNCT") and self._cur().value == "["):
            return ""
        self.pos += 1
        dims: list[str] = []
        while True:
            dims.append(str(self._eat("INT").value) if self._check("INT") else "")
            if self._try_eat("PUNCT", ",") is None:
                break
        self._eat("PUNCT", "]")
        return "[" + ",".join(dims) + "]"

    def _at_tuple_type(self) -> bool:
        """Whether a type starts here and is a tuple's."""
        return self._check("PUNCT") and self._cur().value == "("

    def _parse_tuple_type(self) -> str:
        """Parse: '(' type (',' type)+ ')'

        A tuple's type is written as its values are, so `(i64, str)` is
        the type of `(1i64, "two")`.  One element is not a tuple --
        `(i64)` is a type in parentheses and reads as that type -- and
        the elements are types in their own right, so they may be
        arrays, optionals, or tuples again.

        The text is rebuilt rather than kept as written, so that two
        spellings of one type are one string.
        """
        self._eat("PUNCT", "(")
        elements = [self._parse_type()]
        while self._try_eat("PUNCT", ","):
            elements.append(self._parse_type())
        self._eat("PUNCT", ")")
        if len(elements) == 1:
            return elements[0]
        return "(" + ", ".join(elements) + ")"

    def _parse_type(self) -> str:
        """Parse a type: a name or a tuple, with array and optional suffixes."""
        if self._at_tuple_type():
            written = self._parse_tuple_type()
        else:
            written = self._eat("IDENT").value
        self._reject_unit_here()
        written += self._parse_array_suffix()
        if self._check("OP") and self._cur().value == "?":
            self.pos += 1
            written += "?"
            if self._check("IDENT"):
                written += self._parse_dotted_name()
        elif self._check("OP") and self._cur().value == "!":
            self.pos += 1
            written += "?std.errors"
        return written

    # ------------------------------------------------------------------
    # Top-level parsing
    # ------------------------------------------------------------------

    def parse(self):
        """Parse the full token stream into a list of top-level definitions."""
        definitions = []
        while not self._check("EOF"):
            while self._try_eat("NEWLINE"):
                pass
            # Skip stray INDENT/DEDENT at top level.
            while self._check("INDENT", "DEDENT"):
                self.pos += 1
            definition = self._parse_definition()
            if definition is not None:
                definitions.append(definition)
        return definitions

    def parse_repl(self):
        """Parse interactive input as a mix of definitions and statements.

        A source file may only contain definitions, but the REPL also
        accepts the statements and expressions that would otherwise have
        to be wrapped in a function.  Input starting with a definition
        keyword or annotation is parsed as a definition; anything else is
        parsed as a statement, so a bare expression arrives as ExprStmt.
        """
        items = []
        while not self._check("EOF"):
            while self._try_eat("NEWLINE"):
                pass
            while self._check("INDENT", "DEDENT"):
                self.pos += 1
            if self._check("EOF"):
                break
            if self._cur().type in DEFINITION_STARTERS:
                item = self._parse_definition()
            else:
                item = self._parse_statement()
            if item is not None:
                items.append(item)
        return items

    def _parse_definition(self):
        """Parse a single top-level definition (function, const, enum, or variable)."""
        is_start = False
        is_test = False
        is_flag = False
        is_replaceable = False
        is_impure = False
        is_listable = False
        hint: str | None = None
        repr_kind: str | None = None
        test_refs: list[str] = []
        expect_annotations: list[tuple[str, str]] = []

        while True:
            if self._check("START"):
                self._eat("START")
                is_start = True
                self._try_eat("NEWLINE")
            elif self._check("REPLACEABLE"):
                self._eat("REPLACEABLE")
                is_replaceable = True
                self._try_eat("NEWLINE")
            elif self._check("TEST"):
                self._eat("TEST")
                is_test = True
                if self._check("PUNCT") and self._cur().value == "(":
                    self._eat("PUNCT", "(")
                    while not (self._check("PUNCT") and self._cur().value == ")"):
                        test_refs.append(self._eat("IDENT").value)
                        if not self._try_eat("PUNCT", ","):
                            break
                    self._eat("PUNCT", ")")
                self._try_eat("NEWLINE")
            elif self._check("FLAG"):
                self._eat("FLAG")
                is_flag = True
                self._try_eat("NEWLINE")
            elif self._check("IMPURE"):
                self._eat("IMPURE")
                is_impure = True
                self._try_eat("NEWLINE")
            elif self._check("LISTABLE"):
                self._eat("LISTABLE")
                is_listable = True
                self._try_eat("NEWLINE")
            elif self._check("LIKELY") or self._check("UNLIKELY"):
                tok = self._cur()
                raise ParseError(
                    f"@{tok.value} applies to an if statement, not to a "
                    f"definition; @hot and @cold are the hints for a function",
                    tok)
            elif self._check("HOT") or self._check("COLD"):
                tok = self._eat(self._cur().type)
                other = "cold" if tok.type == "HOT" else "hot"
                if hint == other:
                    raise ParseError(
                        f"@{tok.value} contradicts @{other} on the same "
                        f"function", tok)
                hint = tok.value
                self._try_eat("NEWLINE")
            elif self._check("REPR"):
                repr_kind = self._parse_repr_annotation()
                self._try_eat("NEWLINE")
            elif self._check("EXPECT"):
                self._eat("EXPECT")
                if not self._check("IDENT"):
                    raise ParseError("expected 'error' or 'warning' after @expect", self._cur())
                level_tok = self._eat("IDENT")
                if level_tok.value not in ("error", "warning"):
                    raise ParseError(
                        f"expected 'error' or 'warning' after @expect, got '{level_tok.value}'",
                        level_tok)
                if not self._check("STR"):
                    raise ParseError("expected string pattern after @expect level", self._cur())
                pattern_tok = self._eat("STR")
                expect_annotations.append((level_tok.value, pattern_tok.value))
                self._try_eat("NEWLINE")
            else:
                break

        if hint is not None and not self._check("FN"):
            raise ParseError(
                f"@{hint} applies to a function, but none follows",
                self._cur())
        if is_listable and not self._check("FN"):
            raise ParseError(
                "@listable applies to a function, but none follows",
                self._cur())

        if self._check("ENUM"):
            return self._parse_enum_def(is_flag)

        if self._check("STRUCT"):
            return self._parse_struct_def(repr_kind)

        if repr_kind is not None:
            raise ParseError(
                f"@repr({repr_kind}) applies to a struct, but none follows",
                self._cur())

        if self._check("IMPL"):
            return self._parse_impl_block()

        if self._check("UNIT"):
            return self._parse_unit_def()

        if self._check("TYPE"):
            return self._parse_type_def()

        if self._check("FN"):
            return self._parse_function_def(is_start, is_test, test_refs, expect_annotations,
                                            is_replaceable, is_impure, hint=hint,
                                            is_listable=is_listable)
        elif self._check("LET"):
            return self._parse_var_def()
        elif self._check("EOF"):
            return None  # end of file reached cleanly
        else:
            raise ParseError(
                f"expected function or variable definition, "
                f"got {self._tok_display(self._cur())}",
                self._cur())

    def _parse_function_def(self, is_start, is_test=False, test_refs=None,
                            expect_annotations: list[tuple[str, str]] | None = None,
                            is_replaceable: bool = False,
                            is_impure: bool = False,
                            struct_name: str | None = None,
                            hint: str | None = None,
                            is_listable: bool = False):
        """Parse: fn name '(' [params] ')' ('->' ret_type)? block

        The parameter list is enclosed in parentheses.  An empty parameter
        list is written as ``()``.

        When @expect annotations are present, parse errors in the body are
        captured instead of propagated — the FuncDef stores the error message
        so main.py can match it against expected patterns.

        When struct_name is set, handles self / mut self as the first parameter.
        """
        kw_tok = self._eat("FN")
        name_tok = self._eat("IDENT")
        name = name_tok.value

        params = []
        param_units: dict[str, object] = {}
        param_refs: set[str] = set()
        param_muts: set[str] = set()
        param_positions: dict[str, tuple[int, int, int | None]] = {}
        pack_param: tuple[str, str | None] | None = None
        self._eat("PUNCT", "(")

        self_is_ref = False
        if struct_name is not None:
            while self._try_eat("NEWLINE"):
                pass
            if not (self._check("PUNCT") and self._cur().value == ")"):
                if self._check("OP") and self._cur().value == "&":
                    saved = self.pos
                    self.pos += 1
                    if self._check("MUT"):
                        nxt = self.pos + 1
                        if (nxt < len(self.tokens)
                                and self.tokens[nxt].type == "IDENT"
                                and self.tokens[nxt].value == "self"):
                            self._eat("MUT")
                            self._eat("IDENT")
                            params.append(("self", struct_name))
                            param_muts.add("self")
                            self_is_ref = True
                            self._try_eat("NEWLINE")
                            self._try_eat("PUNCT", ",")
                        else:
                            self.pos = saved
                    elif (self._check("IDENT")
                          and self._cur().value == "self"):
                        self._eat("IDENT")
                        params.append(("self", struct_name))
                        self_is_ref = True
                        self._try_eat("NEWLINE")
                        self._try_eat("PUNCT", ",")
                    else:
                        self.pos = saved
                elif self._check("MUT"):
                    next_idx = self.pos + 1
                    if (next_idx < len(self.tokens)
                            and self.tokens[next_idx].type == "IDENT"
                            and self.tokens[next_idx].value == "self"):
                        self._eat("MUT")
                        self._eat("IDENT")
                        params.append(("self", struct_name))
                        param_muts.add("self")
                        self._try_eat("NEWLINE")
                        self._try_eat("PUNCT", ",")
                elif self._check("IDENT") and self._cur().value == "self":
                    self._eat("IDENT")
                    params.append(("self", struct_name))
                    self._try_eat("NEWLINE")
                    self._try_eat("PUNCT", ",")

        while not (self._check("PUNCT") and self._cur().value == ")"):
            while self._try_eat("NEWLINE"):
                pass
            if self._check("PUNCT") and self._cur().value == ")":
                break
            if self._check("PUNCT") and self._cur().value == "(":
                # A parameter may name the elements of a tuple instead
                # of the tuple, as a definition may.
                open_tok = self._cur()
                names = _as_names(self._parse_destructure_names(open_tok))
                param_type = None
                is_mut = False
                if self._try_eat("PUNCT", ":"):
                    if self._try_eat("MUT"):
                        is_mut = True
                    param_type = self._parse_type()
                params.append((names, param_type))
                if is_mut:
                    param_muts.add(names)
                param_positions[names] = (
                    open_tok.line, open_tok.col,
                    self.tokens[self.pos - 1].end_col)
                self._try_eat("NEWLINE")
                if not self._try_eat("PUNCT", ","):
                    break
                continue
            if not self._check("IDENT"):
                break
            param_name_tok = self._eat("IDENT")
            param_positions[param_name_tok.value] = (
                param_name_tok.line, param_name_tok.col, param_name_tok.end_col)
            is_pack = self._try_eat("PUNCT", "\N{HORIZONTAL ELLIPSIS}")
            param_unit = None
            unit_tok = None
            if self._check("OP") and self._cur().value == "\N{CURRENCY SIGN}":
                unit_tok = self._cur()
                self.pos += 1
                param_unit = self._parse_unit_spec()
            param_type = None
            is_ref = False
            is_mut = False
            if self._check("PUNCT") and self._cur().value == ":":
                next_idx = self.pos + 1
                next_is_type = (next_idx < len(self.tokens) and
                                self.tokens[next_idx].type == "IDENT")
                next_is_ref = (next_idx < len(self.tokens) and
                               self.tokens[next_idx].type == "OP" and
                               self.tokens[next_idx].value == "&")
                next_is_mut = (next_idx < len(self.tokens) and
                               self.tokens[next_idx].type == "MUT")
                next_is_tuple = (next_idx < len(self.tokens) and
                                 self.tokens[next_idx].type == "PUNCT" and
                                 self.tokens[next_idx].value == "(")
                if next_is_type or next_is_ref or next_is_mut or next_is_tuple:
                    self._eat("PUNCT", ":")
                    if self._check("OP") and self._cur().value == "&":
                        self.pos += 1
                        is_ref = True
                    if self._try_eat("MUT"):
                        is_mut = True
                    if self._at_tuple_type():
                        param_type = self._parse_tuple_type()
                    else:
                        type_tok = self._eat("IDENT")
                        param_type = type_tok.value
                param_unit = self._unit_after_type(param_unit, unit_tok)
                param_type += self._parse_array_suffix()
                if self._check("OP") and self._cur().value == "?":
                    self.pos += 1
                    param_type += "?"
                    if self._check("IDENT"):
                        param_type += self._parse_dotted_name()
                elif self._check("OP") and self._cur().value == "!":
                    self.pos += 1
                    param_type += "?std.errors"
            if is_pack:
                pack_param = (param_name_tok.value, param_type)
                break
            params.append((param_name_tok.value, param_type))
            if is_ref:
                param_refs.add(param_name_tok.value)
            if is_mut:
                param_muts.add(param_name_tok.value)
            if param_unit is not None:
                param_units[param_name_tok.value] = param_unit
            self._try_eat("NEWLINE")
            if not self._try_eat("PUNCT", ","):
                break
        self._eat("PUNCT", ")")

        # A signature that says nothing about what comes back says the
        # same as one that writes ∅: the function hands nothing back.
        # Writing the arrow is then a choice about emphasis, not about
        # meaning, so `fn f():` and `fn f() → ∅:` are one signature
        # spelled two ways.
        ret_type = "\N{EMPTY SET}"
        ret_unit = None
        # Where the return type was written, so a redundant one can be
        # pointed at.  None when the signature left it off.
        ret_type_pos = None
        arrow_tok = self._cur()
        if self._try_eat("OP", "->"):
            if self._at_tuple_type():
                # Read as any type is, so a tuple return may be an
                # array of tuples or an optional one.
                ret_type = self._parse_type()
                ret_type_pos = (arrow_tok.line, arrow_tok.col,
                                self.tokens[self.pos - 1].end_col)
            elif self._check("IDENT", "NONE", "OPT"):
                ret_tok = self._cur()
                self.pos += 1
                ret_type = ret_tok.value
                ret_type_pos = (arrow_tok.line, arrow_tok.col,
                                ret_tok.end_col)
                # A return type may state a unit against the element
                # type, as a binding does, so a function can hand back
                # a measured value.
                ret_unit = self._unit_after_type(ret_unit, None)
                # A return type may name an array, as a parameter may.
                ret_type += self._parse_array_suffix()
                # And after the brackets, which is how it was first
                # written and which says the same thing.
                if self._check("OP") and self._cur().value == "\N{CURRENCY SIGN}":
                    if ret_unit is not None:
                        raise ParseError(
                            "the return type states a unit twice; write it "
                            "once, either against the element type or after "
                            "the brackets", self._cur())
                    self.pos += 1
                    ret_unit = self._parse_unit_spec()
                if self._check("OP") and self._cur().value == "?":
                    self.pos += 1
                    ret_type += "?"
                    if self._check("IDENT"):
                        ret_type += self._parse_dotted_name()
                elif self._check("OP") and self._cur().value == "!":
                    self.pos += 1
                    ret_type += "?std.errors"

        if expect_annotations:
            try:
                body = self._parse_block()
            except ParseError as e:
                body = []
                fdef = FuncDef(name, params, ret_type, body, is_start, is_test,
                               test_refs, expect_annotations, is_replaceable,
                               pack_param, param_units, is_impure,
                               param_refs=param_refs,
                               param_muts=param_muts, hint=hint,
                               ret_unit=ret_unit, is_listable=is_listable)
                fdef.param_positions = param_positions
                fdef.ret_type_pos = ret_type_pos
                fdef._parse_error = str(e)
                fdef._self_is_ref = self_is_ref
                self._set_pos(fdef, kw_tok)
                self._skip_to_next_definition()
                return fdef
        else:
            body = self._parse_block()
        fdef = FuncDef(name, params, ret_type, body, is_start, is_test,
                       test_refs, expect_annotations, is_replaceable,
                       pack_param, param_units, is_impure,
                       param_refs=param_refs,
                       param_muts=param_muts, hint=hint,
                       ret_unit=ret_unit, is_listable=is_listable)
        fdef.param_positions = param_positions
        fdef.ret_type_pos = ret_type_pos
        fdef._self_is_ref = self_is_ref
        return self._set_pos(fdef, kw_tok)

    def _parse_dotted_name(self) -> str:
        """Parse a possibly dotted name like 'std.errors'."""
        name = self._eat("IDENT").value
        while (self._check("PUNCT") and self._cur().value == "." and
               self.pos + 1 < len(self.tokens) and
               self.tokens[self.pos + 1].type == "IDENT"):
            self.pos += 1
            name += "." + self._eat("IDENT").value
        return name

    def _parse_enum_def(self, is_flag: bool = False):
        """Parse: enum Name [: underlying_type] : INDENT members DEDENT

        Members are: name [= integer_value], one per line or separated by commas.
        """
        kw_tok = self._eat("ENUM")
        name_tok = self._eat("IDENT")
        name = name_tok.value

        underlying_type = None
        if (self._check("PUNCT") and self._cur().value == ":" and
                self.pos + 1 < len(self.tokens) and
                self.tokens[self.pos + 1].type == "IDENT" and
                self.pos + 2 < len(self.tokens) and
                self.tokens[self.pos + 2].type == "PUNCT" and
                self.tokens[self.pos + 2].value == ":"):
            self._eat("PUNCT", ":")
            underlying_type = self._eat("IDENT").value

        self._eat("PUNCT", ":")
        while self._try_eat("NEWLINE"):
            pass
        self._eat("INDENT")

        members: list[tuple[str, int | None]] = []
        while True:
            while self._try_eat("NEWLINE"):
                pass
            if self._check("DEDENT", "EOF"):
                break
            member_name_tok = self._eat("IDENT")
            explicit_value = None
            if self._try_eat("PUNCT", "="):
                val_tok = self._cur()
                negate = False
                if self._check("OP") and val_tok.value == "⁻":
                    negate = True
                    self.pos += 1
                    val_tok = self._cur()
                if val_tok.type != "INT":
                    raise ParseError(
                        f"expected integer value for enum member '{member_name_tok.value}'",
                        val_tok)
                self.pos += 1
                explicit_value = -val_tok.value if negate else val_tok.value
            members.append((member_name_tok.value, explicit_value))
            self._try_eat("PUNCT", ",")
            self._try_eat("PUNCT", ";")
            while self._try_eat("NEWLINE"):
                pass

        self._eat("DEDENT")
        return self._set_pos(
            EnumDef(name, underlying_type, members, is_flag), kw_tok)

    def _parse_repr_annotation(self) -> str:
        """Parse: @repr '(' KIND ')' and return the layout kind."""
        from interp.layout import KNOWN_REPRS

        self._eat("REPR")
        self._eat("PUNCT", "(")
        if not self._check("IDENT"):
            raise ParseError("expected a layout kind after @repr(",
                             self._cur())
        kind_tok = self._eat("IDENT")
        if kind_tok.value not in KNOWN_REPRS:
            known = ", ".join(sorted(KNOWN_REPRS))
            raise ParseError(
                f"unknown layout '{kind_tok.value}' in @repr; known: {known}",
                kind_tok)
        self._eat("PUNCT", ")")
        return kind_tok.value

    def _parse_struct_def(self, repr_kind: str | None = None):
        """Parse: struct Name: INDENT field_definitions DEDENT"""
        kw_tok = self._eat("STRUCT")
        name_tok = self._eat("IDENT")
        name = name_tok.value
        self._eat("PUNCT", ":")
        while self._try_eat("NEWLINE"):
            pass

        fields: list[tuple[str, str]] = []
        field_positions: dict[str, tuple[int, int, int | None]] = {}
        if self._check("INDENT"):
            self._eat("INDENT")
            while True:
                while self._try_eat("NEWLINE"):
                    pass
                if self._check("DEDENT", "EOF"):
                    break
                field_name_tok = self._eat("IDENT")
                self._eat("PUNCT", ":")
                type_tok = self._cur()
                if self._at_tuple_type():
                    field_type = self._parse_tuple_type()
                else:
                    self.pos += 1
                    field_type = type_tok.value
                field_type += self._parse_array_suffix()
                if self._check("OP") and self._cur().value == "?":
                    self.pos += 1
                    field_type += "?"
                fields.append((field_name_tok.value, field_type))
                # The span runs from the type's first token through the
                # last one an array suffix or `?` added.
                field_positions[field_name_tok.value] = (
                    type_tok.line, type_tok.col,
                    self.tokens[self.pos - 1].end_col)
                self._try_eat("PUNCT", ",")
                while self._try_eat("NEWLINE"):
                    pass
            self._eat("DEDENT")
        sdef = StructDef(name, fields, repr_kind)
        sdef.field_positions = field_positions
        return self._set_pos(sdef, kw_tok)

    def _parse_impl_block(self):
        """Parse: impl StructName: INDENT method_definitions DEDENT"""
        self._eat("IMPL")
        name_tok = self._eat("IDENT")
        struct_name = name_tok.value
        self._eat("PUNCT", ":")
        while self._try_eat("NEWLINE"):
            pass
        self._eat("INDENT")

        methods: list[FuncDef] = []
        while True:
            while self._try_eat("NEWLINE"):
                pass
            if self._check("DEDENT", "EOF"):
                break
            is_impure = False
            is_listable = False
            hint: str | None = None
            while True:
                if self._check("IMPURE"):
                    self._eat("IMPURE")
                    is_impure = True
                    self._try_eat("NEWLINE")
                elif self._check("LISTABLE"):
                    self._eat("LISTABLE")
                    is_listable = True
                    self._try_eat("NEWLINE")
                elif self._check("HOT") or self._check("COLD"):
                    tok = self._eat(self._cur().type)
                    other = "cold" if tok.type == "HOT" else "hot"
                    if hint == other:
                        raise ParseError(
                            f"@{tok.value} contradicts @{other} on the same "
                            f"method", tok)
                    hint = tok.value
                    self._try_eat("NEWLINE")
                else:
                    break
            if not self._check("FN"):
                raise ParseError(
                    f"expected 'fn' in impl block, got "
                    f"{self._tok_display(self._cur())}",
                    self._cur())
            method = self._parse_function_def(
                is_start=False, struct_name=struct_name,
                is_impure=is_impure, hint=hint, is_listable=is_listable)
            methods.append(method)
        self._eat("DEDENT")
        return ImplBlock(struct_name, methods)

    def _skip_to_next_definition(self):
        """Advance past tokens until we reach the next top-level definition.

        Used for error recovery in @expect-annotated functions.
        """
        depth = 0
        while not self._check("EOF"):
            tok = self._cur()
            if tok.type == "INDENT":
                depth += 1
                self.pos += 1
            elif tok.type == "DEDENT":
                depth -= 1
                self.pos += 1
                if depth <= 0:
                    break
            elif tok.type == "PUNCT" and tok.value == "{":
                depth += 1
                self.pos += 1
            elif tok.type == "PUNCT" and tok.value == "}":
                depth -= 1
                self.pos += 1
                if depth <= 0:
                    break
            else:
                self.pos += 1

    def _parse_destructure_names(self, kw_tok):
        """Parse the parenthesized names a destructuring binds.

        One entry per element, in the order the tuple has them, so what
        the definition looks like is what it takes apart.  An entry may
        be a parenthesized list of its own, which takes apart an
        element that is itself a tuple.  The discard target stands
        where an element is not wanted.
        """
        self._eat("PUNCT", "(")
        names: list = []
        while True:
            if self._check("PUNCT") and self._cur().value == "(":
                names.append(self._parse_destructure_names(kw_tok))
            else:
                names.append(self._eat("IDENT").value)
            if not self._try_eat("PUNCT", ","):
                break
        self._eat("PUNCT", ")")
        if len(names) < 2:
            raise ParseError(
                "a definition taking a tuple apart needs a name for each "
                "element, and a tuple has at least two", kw_tok)
        return names

    def _parse_destructure_def(self, kw_tok):
        """Parse: let '(' names ')' [: [mut] type] = expr"""
        names = self._parse_destructure_names(kw_tok)
        seen: set[str] = set()
        pending = list(names)
        while pending:
            entry = pending.pop()
            if isinstance(entry, list):
                pending.extend(entry)
                continue
            if entry == "_":
                continue
            if entry in seen:
                raise ParseError(
                    f"the definition names '{entry}' twice; each element "
                    f"needs a name of its own", kw_tok)
            seen.add(entry)

        type_annotation = None
        is_const = True
        if self._try_eat("PUNCT", ":"):
            if self._try_eat("MUT"):
                is_const = False
            if not (self._check("PUNCT") and self._cur().value == "="):
                type_annotation = self._parse_type()
        self._eat("PUNCT", "=")
        init_expr = self._parse_or_expr()
        self._try_eat("PUNCT", ";")
        return self._set_pos(
            DestructureDef(names, type_annotation, init_expr, is_const),
            kw_tok)

    def _parse_var_def(self):
        """Parse: let name [¤unit] := expr  |  let name [¤unit] : [mut] type = expr  |  let name : mut type[size] = init"""
        kw_tok = self._cur()
        self._eat("LET")
        keyword = "let"
        if self._check("PUNCT") and self._cur().value == "(":
            return self._parse_destructure_def(kw_tok)
        name_tok = self._eat("IDENT")

        unit_spec = None
        unit_tok = None
        if self._check("OP") and self._cur().value == "\N{CURRENCY SIGN}":
            unit_tok = self._cur()
            self.pos += 1
            unit_spec = self._parse_unit_spec()

        type_annotation = None
        is_const = True
        has_colon = self._try_eat("PUNCT", ":")
        if has_colon:
            if self._try_eat("MUT"):
                is_const = False
            if self._at_tuple_type():
                # A tuple type is read whole, so what may follow it is
                # what may follow any type: brackets making an array of
                # it, and ? or ! making it optional.
                type_annotation = self._parse_tuple_type()
                unit_spec = self._unit_after_type(unit_spec, unit_tok)
                type_annotation += self._parse_array_suffix()
                if self._check("OP") and self._cur().value == "?":
                    self.pos += 1
                    type_annotation += "?"
                elif self._check("OP") and self._cur().value == "!":
                    self.pos += 1
                    type_annotation += "?std.errors"
            elif self._check("IDENT"):
                type_annotation = self._eat("IDENT").value
                # `i64 ¤meter[]` says what each element is and what it
                # measures, in that order, which is the same thing
                # `let d ¤meter : i64[]` says with the unit written by
                # the name.  Read before the brackets, so the shape
                # that follows is the array's rather than the unit's.
                unit_spec = self._unit_after_type(unit_spec, unit_tok)
                if self._check("PUNCT") and self._cur().value == "[":
                    self.pos += 1
                    if self._check("PUNCT") and self._cur().value == "]":
                        self.pos += 1
                        type_annotation += "[]"
                    else:
                        # One extent per dimension, each an expression so
                        # that a length can be computed rather than only
                        # written out, or empty to take that dimension
                        # from the initializer.
                        def extent():
                            if self._check("PUNCT") and self._cur().value in (",", "]"):
                                return None
                            return self._parse_or_expr()

                        dims = [extent()]
                        while self._try_eat("PUNCT", ","):
                            dims.append(extent())
                        self._eat("PUNCT", "]")
                        self._eat("PUNCT", "=")
                        init_expr = self._parse_or_expr()
                        self._try_eat("PUNCT", ";")
                        return self._set_pos(VarDef(name_tok.value, type_annotation,
                                      ArrayAlloc(type_annotation, dims[0], init_expr,
                                                 rest_dims=dims[1:]),
                                  is_const, unit_spec=unit_spec), kw_tok)

                # An optional or expected binding, spelled as it is in a
                # signature or a type alias.
                if self._check("OP") and self._cur().value == "?":
                    self.pos += 1
                    type_annotation += "?"
                    if self._check("IDENT"):
                        type_annotation += self._parse_dotted_name()
                elif self._check("OP") and self._cur().value == "!":
                    self.pos += 1
                    type_annotation += "?std.errors"

        if not has_colon:
            if not (self._check("PUNCT") and self._cur().value == ":"):
                raise ParseError(
                    f"{keyword} definition requires ':=' or ': [mut] type ='",
                    self._cur())
            self._eat("PUNCT", ":")
        self._eat("PUNCT", "=")
        init_expr = self._parse_or_expr()
        self._try_eat("PUNCT", ";")

        return self._set_pos(VarDef(name_tok.value, type_annotation, init_expr, is_const,
                      unit_spec=unit_spec), kw_tok)

    # ------------------------------------------------------------------
    # Unit definition and spec parsing
    # ------------------------------------------------------------------

    def _parse_type_def(self):
        """Parse: type NAME = TARGET_TYPE"""
        kw_tok = self._cur()
        self._eat("TYPE")
        name_tok = self._eat("IDENT")
        self._eat("PUNCT", "=")
        type_tok = self._cur()
        if self._at_tuple_type():
            target = self._parse_tuple_type()
        else:
            self.pos += 1
            target = type_tok.value
        self._reject_unit_here()
        target += self._parse_array_suffix()
        if self._check("OP") and self._cur().value == "?":
            self.pos += 1
            target += "?"
            if self._check("IDENT"):
                target += self._parse_dotted_name()
        elif self._check("OP") and self._cur().value == "!":
            self.pos += 1
            target += "?std.errors"

        # `type N = A | B` names a choice between types rather than
        # another name for one of them.
        if self._check("OP") and self._cur().value == "|":
            alternatives = [target]
            while self._check("OP") and self._cur().value == "|":
                self.pos += 1
                alt_tok = self._eat("IDENT")
                alt = alt_tok.value + self._parse_array_suffix()
                if alt in alternatives:
                    raise ParseError(
                        f"'{alt}' is named twice in the alternatives of "
                        f"'{name_tok.value}'", alt_tok)
                alternatives.append(alt)
            self._try_eat("PUNCT", ";")
            return self._set_pos(
                SumTypeDef(name_tok.value, alternatives), kw_tok)

        self._try_eat("PUNCT", ";")
        return self._set_pos(TypeDef(name_tok.value, target), kw_tok)

    def _parse_unit_def(self):
        """Parse: unit name [= formula]"""
        kw_tok = self._eat("UNIT")
        name_tok = self._eat("IDENT")
        formula = None
        if self._try_eat("PUNCT", "="):
            formula = self._parse_unit_formula()
        self._try_eat("PUNCT", ";")
        return self._set_pos(UnitDef(name_tok.value, formula), kw_tok)

    def _reject_unit_here(self):
        """Refuse a unit written where a unit cannot yet be said.

        A unit belongs to a binding or to what an array holds.  Written
        into a type alias or a tuple element it would have to belong to
        the type itself, which is the question a sum or product type
        raises and which is not answered yet.
        """
        if self._check("OP") and self._cur().value == "\N{CURRENCY SIGN}":
            raise ParseError(
                "a unit belongs to a binding or to what an array holds; "
                "a type alias or a tuple element cannot state one yet",
                self._cur())

    def _unit_after_type(self, unit_spec, unit_tok):
        """Read a unit written against the element type, if one is there.

        The two positions say the same thing -- what each of the
        values counts -- so writing both would be saying it twice
        rather than saying two things, and is refused.
        """
        if not (self._check("OP")
                and self._cur().value == "\N{CURRENCY SIGN}"):
            return unit_spec
        tok = self._cur()
        if unit_spec is not None:
            raise ParseError(
                "the definition states a unit twice; write it once, "
                "either after the name or against the element type",
                unit_tok or tok)
        self.pos += 1
        return self._parse_unit_spec()

    def _parse_unit_spec(self):
        """Parse a unit specification after ¤ (no numeric literals)."""
        left = self._parse_unit_atom()
        while self._check("OP") and self._cur().value in ("\N{MULTIPLICATION SIGN}", "\N{DIVISION SIGN}"):
            next_pos = self.pos + 1
            if next_pos >= len(self.tokens):
                break
            nxt = self.tokens[next_pos]
            if nxt.type not in ("IDENT", "STR") and \
               not (nxt.type == "OP" and nxt.value == "\N{SQUARE ROOT}"):
                break
            op = self._cur().value
            self.pos += 1
            right = self._parse_unit_atom()
            left = UnitBinOp(op, left, right)
        return left

    def _parse_unit_atom(self):
        """Parse a single unit atom: ident, string, or √unit."""
        if self._check("OP") and self._cur().value == "\N{SQUARE ROOT}":
            self.pos += 1
            operand = self._parse_unit_atom()
            return UnitSqrt(operand)
        if self._check("IDENT"):
            name = self._eat("IDENT").value
            return UnitName(name, is_string=False)
        if self._check("STR"):
            name = self._eat("STR").value
            return UnitName(name, is_string=True)
        raise ParseError("expected unit name", self._cur())

    def _parse_unit_formula(self):
        """Parse a unit formula in a unit definition (allows numeric factors)."""
        left = self._parse_unit_def_atom()
        while self._check("OP") and self._cur().value in ("\N{MULTIPLICATION SIGN}", "\N{DIVISION SIGN}"):
            op = self._cur().value
            self.pos += 1
            right = self._parse_unit_def_atom()
            left = UnitBinOp(op, left, right)
        return left

    def _parse_unit_def_atom(self):
        """Parse a unit definition atom: ident, string, integer, or √unit."""
        if self._check("OP") and self._cur().value == "\N{SQUARE ROOT}":
            self.pos += 1
            operand = self._parse_unit_def_atom()
            return UnitSqrt(operand)
        if self._check("INT"):
            val = self._eat("INT").value
            return UnitLit(val)
        if self._check("IDENT"):
            name = self._eat("IDENT").value
            return UnitName(name, is_string=False)
        if self._check("STR"):
            name = self._eat("STR").value
            return UnitName(name, is_string=True)
        raise ParseError("expected unit name or number", self._cur())

    # ------------------------------------------------------------------
    # Block parsing (brace-delimited or layout-driven)
    # ------------------------------------------------------------------

    def _parse_block(self):
        """Parse a block, dispatching to brace or layout style."""
        if self._check("PUNCT") and self._cur().value == "{":
            return self._parse_brace_block()
        if self._check("PUNCT") and self._cur().value == ":":
            return self._parse_layout_block()
        raise ParseError("expected '{' or ':' to begin block", self._cur())

    def _parse_brace_block(self):
        """Parse a brace-delimited block: { stmts }.

        INDENT/DEDENT tokens are skipped as noise inside braces.
        """
        self._eat("PUNCT", "{")
        stmts = []
        while True:
            while not self._check("EOF") and self._cur().type in ("NEWLINE", "INDENT", "DEDENT"):
                self.pos += 1
            if self._check("EOF") or (self._cur().type == "PUNCT" and self._cur().value == "}"):
                break
            stmt = self._parse_statement()
            if stmt is not None:
                stmts.append(stmt)
        self._eat("PUNCT", "}")
        return stmts

    def _parse_layout_block(self):
        """Parse a layout-driven block: : INDENT stmts DEDENT.

        A single statement on the same line as the colon is also accepted.
        """
        self._eat("PUNCT", ":")
        while self._try_eat("NEWLINE"):
            pass
        if not self._check("INDENT"):
            stmt = self._parse_statement()
            return [stmt] if stmt else []
        self._eat("INDENT")
        stmts = []
        while True:
            while self._try_eat("NEWLINE"):
                pass
            if self._check("DEDENT", "EOF"):
                break
            stmt = self._parse_statement()
            if stmt is not None:
                stmts.append(stmt)
        self._eat("DEDENT")
        return stmts

    # ------------------------------------------------------------------
    # Statement parsing
    # ------------------------------------------------------------------

    def _parse_statement(self):
        """Parse a single statement."""
        while self._try_eat("NEWLINE"):
            pass

        if self._check("EOF"):
            return None

        if self._check("EXPECT"):
            return self._parse_expect_stmt()

        if self._check("LET"):
            return self._parse_var_def()

        if self._check("TYPE"):
            return self._parse_type_def()

        if self._check("LIKELY") or self._check("UNLIKELY"):
            return self._parse_hinted_if()

        if self._check("IF"):
            return self._parse_if_stmt()

        if self._check("WHILE"):
            return self._parse_while_stmt()

        if self._check("COMPTIME"):
            if (self.pos + 1 < len(self.tokens) and
                    self.tokens[self.pos + 1].type == "FOREACH"):
                self._eat("COMPTIME")
                return self._parse_foreach_stmt(is_comptime=True)

        if self._check("FOREACH"):
            return self._parse_foreach_stmt()

        if self._check("MATCH"):
            return self._parse_match_stmt()

        if self._check("CATCH"):
            return self._parse_catch_stmt()

        if self._check("RETURN"):
            return self._parse_return_stmt()

        # General assignment: LHS ← RHS.  `=` is equality and never
        # stores, which is what lets the same glyph be the operator: a
        # statement is an assignment when it holds a ←, and anything
        # else beginning with a name is an expression.
        if self._check("IDENT") or (self._check("PUNCT") and self._cur().value == "("):
            saved_pos = self.pos
            bracket_depth = 0
            found_assign_op = None
            while saved_pos < len(self.tokens):
                t = self.tokens[saved_pos]
                if t.type in ("NEWLINE", "INDENT", "DEDENT") or (t.type == "PUNCT" and t.value == ";"):
                    break
                if t.type == "PUNCT":
                    if t.value == "[": bracket_depth += 1
                    elif t.value == "]": bracket_depth -= 1
                if t.type == "OP" and t.value == "←" and bracket_depth == 0:
                    found_assign_op = "←"
                    break
                saved_pos += 1

            if found_assign_op:
                lhs = self._parse_or_expr()
                self._eat("OP", "←")
                rhs = self._parse_or_expr()
                self._try_eat("PUNCT", ";")
                return ("assign_stmt", lhs, rhs)

        expr = self._parse_or_expr()
        self._try_eat("PUNCT", ";")
        return ExprStmt(expr)

    def _parse_if_stmt(self, hint: str | None = None):
        """Parse: if expr block (elif expr block)* (else block)?"""
        self._eat("IF")
        cond = self._parse_or_expr()
        cons_body = self._parse_block()

        # Collected in source order, then nested so that the first
        # clause is the outermost: the evaluator walks from the outside
        # in, and a chain built the other way would test the last
        # clause first.
        clauses: list[tuple[object, list]] = []
        while True:
            self._skip_nl()
            if self._check("ELIF"):
                self._eat("ELIF")
                elif_cond = self._parse_or_expr()
                clauses.append((elif_cond, self._parse_block()))
            elif self._check("ELSE"):
                self._eat("ELSE")
                clauses.append((None, self._parse_block()))
            else:
                break

        alt = None
        for clause_cond, clause_body in reversed(clauses):
            alt = ((clause_cond, clause_body) if alt is None
                   else (clause_cond, clause_body, alt))

        return IfStmt(cond, cons_body, alt, hint=hint)

    def _parse_while_stmt(self):
        """Parse: while [var [: type]] ':=' expr block, or while expr block

        The binding form mirrors foreach: the expression is evaluated
        afresh each time round, bound to the variable, and its value is
        what the loop tests.
        """
        self._eat("WHILE")
        var_name = None
        var_type = None
        var_is_mut = False
        if self._at_while_binding():
            var_name = self._eat("IDENT").value
            self._eat("PUNCT", ":")
            if self._try_eat("MUT"):
                var_is_mut = True
            if self._check("IDENT"):
                var_type = self._eat("IDENT").value
                if self._check("OP") and self._cur().value == "?":
                    self.pos += 1
                    var_type += "?"
            self._eat("PUNCT", "=")
        cond = self._parse_or_expr()
        body = self._parse_block()
        return WhileStmt(cond, body, var_name, var_type, var_is_mut)

    def _at_while_binding(self) -> bool:
        """Tell `while e := expr:` from a plain condition `while e:`.

        Both start with an identifier and a colon; what follows decides.
        A '=' next is the untyped binding.  A type name followed by '='
        is the typed one -- which an inline body that happens to be an
        assignment would also look like, so such a body has to be
        written as an indented block.
        """
        if not self._check("IDENT"):
            return False
        after = self.tokens[self.pos + 1] if self.pos + 1 < len(self.tokens) else None
        if after is None or after.type != "PUNCT" or after.value != ":":
            return False
        third = self.tokens[self.pos + 2] if self.pos + 2 < len(self.tokens) else None
        if third is None:
            return False
        if third.type == "PUNCT" and third.value == "=":
            return True
        if third.type == "MUT":
            return True
        if third.type != "IDENT":
            return False
        fourth = self.tokens[self.pos + 3] if self.pos + 3 < len(self.tokens) else None
        return (fourth is not None and fourth.type == "PUNCT"
                and fourth.value == "=")

    def _parse_foreach_stmt(self, is_comptime: bool = False):
        """Parse: [comptime] foreach var1 [: type1] [, var2 [: type2]] := expr1 [, expr2] block
        When a type annotation is present the = suffices (: already consumed);
        without a type annotation := is required."""
        self._eat("FOREACH")
        vars_list: list[tuple[str, str | None]] = []
        last_has_type = False
        while True:
            name_tok = self._eat("IDENT")
            var_type = None
            last_has_type = False
            if (self._check("PUNCT") and self._cur().value == ":" and
                    self.pos + 1 < len(self.tokens) and
                    self.tokens[self.pos + 1].type == "IDENT"):
                self._eat("PUNCT", ":")
                var_type = self._eat("IDENT").value
                last_has_type = True
                if self._check("OP") and self._cur().value == "?":
                    self.pos += 1
                    var_type += "?"
                    if self._check("IDENT"):
                        var_type += self._parse_dotted_name()
                elif self._check("OP") and self._cur().value == "!":
                    self.pos += 1
                    var_type += "?std.errors"
            vars_list.append((name_tok.value, var_type))
            if not self._try_eat("PUNCT", ","):
                break
        if not last_has_type:
            if not (self._check("PUNCT") and self._cur().value == ":"):
                raise ParseError("foreach without type annotation requires ':='", self._cur())
            self._eat("PUNCT", ":")
        self._eat("PUNCT", "=")
        iterables = []
        while True:
            iterables.append(self._parse_iterable())
            if not self._try_eat("PUNCT", ","):
                break
        body = self._parse_block()
        return ForEachStmt(vars_list, iterables, body, is_comptime)

    def _parse_iterable(self):
        """Parse one foreach iterable, which may be borrowed.

        `&expr` iterates the elements for reading; `&mut expr` iterates
        them for writing, so the loop variable refers to the element
        rather than to a copy of it.
        """
        if self._check("OP") and self._cur().value == "&":
            amp_tok = self._eat("OP", "&")
            is_mut = self._try_eat("MUT") is not None
            return self._set_pos(BorrowExpr(self._parse_or_expr(), is_mut),
                                 amp_tok)
        return self._parse_or_expr()

    def _parse_match_stmt(self):
        """Parse: match expr: INDENT arm+ DEDENT

        Each arm is a pattern, a colon, and a body -- either statements
        on the same line or an indented block, as elsewhere.
        """
        kw_tok = self._eat("MATCH")
        subject = self._parse_or_expr()
        self._eat("PUNCT", ":")
        while self._try_eat("NEWLINE"):
            pass
        if not self._check("INDENT"):
            raise ParseError("match requires an indented list of arms",
                             self._cur())
        self._eat("INDENT")

        arms: list[MatchArm] = []
        while True:
            while self._try_eat("NEWLINE"):
                pass
            if self._check("DEDENT", "EOF"):
                break
            arms.append(self._parse_match_arm())
        self._eat("DEDENT")
        if not arms:
            raise ParseError("match requires at least one arm", kw_tok)
        return self._set_pos(MatchStmt(subject, arms), kw_tok)

    def _parse_arm_binding(self):
        """Parse what an arm binds: a name, or a tuple's elements.

        `∃(v)` names the matched value and
        `∃((a, b))` names the elements of it, in the
        shape a definition or a parameter uses.
        """
        self._eat("PUNCT", "(")
        if self._check("PUNCT") and self._cur().value == "(":
            names = _as_names(self._parse_destructure_names(self._cur()))
            self._eat("PUNCT", ")")
            return names
        name = self._eat("IDENT").value
        self._eat("PUNCT", ")")
        return name

    def _parse_match_arm(self) -> MatchArm:
        """Parse one arm: ∃(name) | ∅ | _  followed by ':' and a body."""
        kind: str
        name = None
        pattern_tok = self._cur()
        if self._check("SOME"):
            self.pos += 1
            name = self._parse_arm_binding()
            kind = "some"
        elif self._check("NOTEXISTS"):
            self.pos += 1
            name = self._parse_arm_binding()
            kind = "err"
        elif self._check("NONE"):
            self.pos += 1
            kind = "none"
        elif (self._check("IDENT") and self._cur().value == "_"):
            self.pos += 1
            kind = "wildcard"
        elif self._check("IDENT"):
            # Type(name): an alternative of a sum type, binding the
            # value under the type that says which alternative it is.
            type_tok = self._eat("IDENT")
            type_name = type_tok.value
            name = self._parse_arm_binding()
            kind = "type"
            body = self._parse_block()
            return self._set_pos(
                MatchArm(kind, name, body, type_name=type_name),
                pattern_tok)
        else:
            raise ParseError(
                "expected a match pattern: \N{THERE EXISTS}(name), "
                "\N{THERE DOES NOT EXIST}(name), \N{EMPTY SET}, "
                "Type(name), or _",
                self._cur())
        body = self._parse_block()
        return self._set_pos(MatchArm(kind, name, body), pattern_tok)

    def _parse_catch_stmt(self):
        """Parse: catch block"""
        self._eat("CATCH")
        body = self._parse_block()
        return CatchStmt(body)

    def _parse_return_stmt(self):
        """Parse: return [expr]"""
        self._eat("RETURN")
        value = None
        if not self._check("EOF", "NEWLINE", "DEDENT") and \
           not (self._cur().type == "PUNCT" and self._cur().value == "}"):
            value = self._parse_or_expr()
        self._try_eat("PUNCT", ";")
        return ReturnStmt(value)

    def _parse_hinted_if(self):
        """Parse: (@likely | @unlikely) if ...

        The hint says which way the condition is expected to go, so it
        belongs to the `if` and to nothing else.
        """
        tok = self._eat(self._cur().type)
        hint = tok.value
        other = "unlikely" if hint == "likely" else "likely"
        self._skip_nl()
        while self._check("LIKELY") or self._check("UNLIKELY"):
            dup = self._eat(self._cur().type)
            if dup.value != hint:
                raise ParseError(
                    f"@{dup.value} contradicts @{hint} on the same condition",
                    dup)
            raise ParseError(f"@{hint} is given twice on the same condition", dup)
        if not self._check("IF"):
            raise ParseError(
                f"@{hint} applies to an if statement, but none follows",
                self._cur())
        return self._parse_if_stmt(hint=hint)

    def _parse_expect_stmt(self):
        """Parse: @expect (error|warning) "pattern" \\n statement"""
        expectations: list[tuple[str, str]] = []
        while self._check("EXPECT"):
            self._eat("EXPECT")
            if not self._check("IDENT"):
                raise ParseError("expected 'error' or 'warning' after @expect", self._cur())
            level_tok = self._eat("IDENT")
            if level_tok.value not in ("error", "warning"):
                raise ParseError(
                    f"expected 'error' or 'warning' after @expect, got '{level_tok.value}'",
                    level_tok)
            if not self._check("STR"):
                raise ParseError("expected string pattern after @expect level", self._cur())
            pattern_tok = self._eat("STR")
            expectations.append((level_tok.value, pattern_tok.value))
            self._try_eat("NEWLINE")
            while self._try_eat("NEWLINE"):
                pass
        stmt = self._parse_statement()
        return ExpectStmt(expectations, stmt)

    def _parse_lambda(self):
        """Parse: λ [param1 : type1 [, paramN : typeN]] [|capture1 [, captureN]|] -> ret_type : expr"""
        lambda_tok = self._cur()
        self._eat("LAMBDA")
        params: list[tuple[str, str]] = []
        while (self._check("IDENT")
               or (self._check("PUNCT") and self._cur().value == "(")):
            saved = self.pos
            if self._check("PUNCT") and self._cur().value == "(":
                open_tok = self._cur()
                names = _as_names(self._parse_destructure_names(open_tok))
                ptype = None
                if self._try_eat("PUNCT", ":"):
                    ptype = self._parse_type()
                params.append((names, ptype))
                if not self._try_eat("PUNCT", ","):
                    break
                continue
            name = self._eat("IDENT").value
            follows = (self.tokens[self.pos + 1]
                       if self.pos + 1 < len(self.tokens) else None)
            names_type = follows is not None and (
                follows.type == "IDENT"
                or (follows.type == "PUNCT" and follows.value == "("))
            if not (self._check("PUNCT") and self._cur().value == ":"
                    and names_type):
                raise ParseError(
                    f"lambda parameter '{name}' requires a type annotation", self._cur())
            self._eat("PUNCT", ":")
            if self._at_tuple_type():
                ptype = self._parse_tuple_type()
            else:
                ptype = self._eat("IDENT").value
            ptype += self._parse_array_suffix()
            params.append((name, ptype))
            if not self._try_eat("PUNCT", ","):
                break

        captures: list[str] | None = None
        if self._check("OP") and self._cur().value == "|":
            self.pos += 1
            captures = []
            while self._check("IDENT"):
                captures.append(self._eat("IDENT").value)
                if not self._try_eat("PUNCT", ","):
                    break
            if not (self._check("OP") and self._cur().value == "|"):
                raise ParseError("expected '|' to close capture list", self._cur())
            self.pos += 1
            if not captures:
                raise ParseError("empty capture list is not allowed", self._cur())

        if not (self._check("OP") and self._cur().value == "->"):
            raise ParseError("lambda requires a return type (-> type)", self._cur())
        self._eat("OP", "->")
        if not self._check("IDENT", "NONE"):
            raise ParseError("expected return type after '->'", self._cur())
        ret_tok = self._cur()
        self.pos += 1
        ret_type = ret_tok.value
        if self._check("OP") and self._cur().value == "?":
            self.pos += 1
            ret_type += "?"
            if self._check("IDENT"):
                ret_type += self._parse_dotted_name()
        elif self._check("OP") and self._cur().value == "!":
            self.pos += 1
            ret_type += "?std.errors"

        self._eat("PUNCT", ":")
        if self._check("PUNCT") and self._cur().value == "{":
            body = self._parse_brace_block()
        elif self._check("NEWLINE"):
            self._try_eat("NEWLINE")
            while self._try_eat("NEWLINE"):
                pass
            if self._check("INDENT"):
                self._eat("INDENT")
                stmts: list = []
                while True:
                    while self._try_eat("NEWLINE"):
                        pass
                    if self._check("DEDENT", "EOF"):
                        break
                    stmt = self._parse_statement()
                    if stmt is not None:
                        stmts.append(stmt)
                self._eat("DEDENT")
                body = stmts
            else:
                body = self._parse_or_expr()
        else:
            body = self._parse_or_expr()
        return self._set_pos(
            LambdaExpr(params, captures, ret_type, body), lambda_tok)

    # ------------------------------------------------------------------
    # Expression parsing (precedence climbing)
    # ------------------------------------------------------------------

    def _skip_nl(self):
        """Skip any NEWLINE tokens (for multi-line expressions)."""
        while self._check("NEWLINE"):
            self.pos += 1

    def _parse_or_expr(self):
        """or_expr → and_expr ('or' and_expr | '??' and_expr)*"""
        left = self._parse_and_expr()
        while True:
            self._skip_nl()
            or_tok = self._cur()
            if self._try_eat("OR"):
                self._skip_nl()
                right = self._parse_and_expr()
                left = self._set_binop_pos(BinOp("or", left, right), left, right, or_tok)
            elif self._check("OP") and self._cur().value == "??":
                self.pos += 1
                self._skip_nl()
                right = self._parse_and_expr()
                left = self._set_binop_pos(BinOp("??", left, right), left, right, or_tok)
            else:
                break
        return left

    def _parse_and_expr(self):
        """and_expr → logic_or_expr ('and' logic_or_expr)*"""
        left = self._parse_logic_or_expr()
        while True:
            self._skip_nl()
            and_tok = self._cur()
            if not self._try_eat("AND"):
                break
            self._skip_nl()
            right = self._parse_logic_or_expr()
            left = self._set_binop_pos(BinOp("and", left, right), left, right, and_tok)
        return left

    def _parse_logic_or_expr(self):
        """logic_or_expr → logic_xor_expr (('∨' | '⊽') logic_xor_expr)*"""
        left = self._parse_logic_xor_expr()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value in ("∨", "⊽")):
                break
            op_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_logic_xor_expr()
            left = self._set_binop_pos(BinOp(op_tok.value, left, right), left, right, op_tok)
        return left

    def _parse_logic_xor_expr(self):
        """logic_xor_expr → logic_and_expr ('⊕' logic_and_expr)*"""
        left = self._parse_logic_and_expr()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value == "⊕"):
                break
            xor_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_logic_and_expr()
            left = self._set_binop_pos(BinOp("⊕", left, right), left, right, xor_tok)
        return left

    def _parse_logic_and_expr(self):
        """logic_and_expr → cmp_expr (('∧' | '⊼') cmp_expr)*"""
        left = self._parse_cmp_expr()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value in ("∧", "⊼")):
                break
            op_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_cmp_expr()
            left = self._set_binop_pos(BinOp(op_tok.value, left, right), left, right, op_tok)
        return left

    _CMP_OPS = ("\N{NOT EQUAL TO}", "<", ">", "<=", ">=",
                "≅", "≇", "⪅", "⪆", "⪉", "⪊")

    def _parse_cmp_expr(self):
        """cmp_expr → range_expr (comparison range_expr)*

        The tolerant comparisons sit at the same level as the exact
        ones they are paired with, since they answer the same question
        with a tolerance rather than a different question.

        Equality is `=`, which the lexer hands over as punctuation
        because the same glyph separates a definition from its value.
        Which one is meant is settled by where it is written: a
        definition consumes its `=` before an expression begins, so one
        reached here is the operator.
        """
        left = self._parse_range_expr()
        while True:
            self._skip_nl()
            if self._check("OP") and self._cur().value in _OLD_CMP_SPELLINGS:
                old = self._cur().value
                raise ParseError(
                    f"'{old}' is not an operator; "
                    f"{_OLD_CMP_SPELLINGS[old]}", self._cur())
            is_eq = self._check("PUNCT") and self._cur().value == "="
            if not (is_eq or (self._check("OP")
                              and self._cur().value in self._CMP_OPS)):
                break
            op_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_range_expr()
            left = self._set_binop_pos(BinOp(op_tok.value, left, right), left, right, op_tok)
        return left

    def _parse_range_expr(self):
        """range_expr → minmax_expr ('…' minmax_expr ('…' minmax_expr)?)?"""
        left = self._parse_minmax_expr()
        if self._check("PUNCT") and self._cur().value == "…":
            self.pos += 1
            second = self._parse_minmax_expr()
            if self._check("PUNCT") and self._cur().value == "…":
                self.pos += 1
                end = self._parse_minmax_expr()
                return RangeExpr(left, end, step=second)
            return RangeExpr(left, second)
        return left

    def _parse_minmax_expr(self):
        """minmax_expr → shift_expr (('⌈' | '⌊' | '⍳' | '∊') shift_expr)*

        Loose enough that the operands may be written as arithmetic --
        `a + b ⌈ c - d` is the larger of the two sums, which is how one
        says it -- and tight enough that a comparison or a range reads
        the answer rather than an operand.  ⍳ and ∊ sit here for the
        same reason: what is looked for is often computed, and what
        comes back is usually asked about rather than combined.
        """
        left = self._parse_shift_expr()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value in _PICK_OPS):
                break
            op_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_shift_expr()
            left = self._set_binop_pos(BinOp(op_tok.value, left, right),
                                       left, right, op_tok)
        return left

    def _parse_shift_expr(self):
        """shift_expr → bitwise_or (('<<' | '>>' | '«' | '»' | '↺' | '↻') bitwise_or)*"""
        left = self._parse_bitwise_or()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value in ("<<", ">>", "«", "»", "↺", "↻")):
                break
            op_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_bitwise_or()
            left = self._set_binop_pos(BinOp(op_tok.value, left, right), left, right, op_tok)
        return left

    def _parse_bitwise_or(self):
        """bitwise_or → bitwise_xor ('|' bitwise_xor)*"""
        left = self._parse_bitwise_xor()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value == "|"):
                break
            op_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_bitwise_xor()
            left = self._set_binop_pos(BinOp("|", left, right), left, right, op_tok)
        return left

    def _parse_bitwise_xor(self):
        """bitwise_xor → bitwise_and ('^' bitwise_and)*"""
        left = self._parse_bitwise_and()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value == "^"):
                break
            op_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_bitwise_and()
            left = self._set_binop_pos(BinOp("^", left, right), left, right, op_tok)
        return left

    def _parse_bitwise_and(self):
        """bitwise_and → add_expr ('&' add_expr)*"""
        left = self._parse_add_expr()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value == "&"):
                break
            op_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_add_expr()
            left = self._set_binop_pos(BinOp("&", left, right), left, right, op_tok)
        return left

    def _parse_add_expr(self):
        """add_expr → concat_expr (('+' | '-' | '⊞' | '⊟') concat_expr)*

        The saturating operators bind as the exact ones they answer to,
        so replacing + with ⊞ in an expression does not regroup it.
        """
        left = self._parse_concat_expr()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value in _ADD_OPS):
                break
            op_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_concat_expr()
            left = self._set_binop_pos(BinOp(op_tok.value, left, right), left, right, op_tok)
        return left

    def _parse_concat_expr(self):
        """concat_expr → mul_expr ('⧺' mul_expr)*"""
        left = self._parse_mul_expr()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value == "\N{DOUBLE PLUS}"):
                break
            concat_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_mul_expr()
            left = self._set_binop_pos(BinOp("\N{DOUBLE PLUS}", left, right), left, right, concat_tok)
        return left

    def _parse_mul_expr(self):
        """mul_expr → reshape (('×' | '÷' | '%' | '⊠') reshape)*"""
        left = self._parse_reshape_expr()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value in _MUL_OPS):
                break
            op_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_reshape_expr()
            left = self._set_binop_pos(BinOp(op_tok.value, left, right), left, right, op_tok)
        return left

    def _parse_reshape_expr(self):
        """reshape_expr → negation (('⍴' | '⌿' | '⍀') …)?

        ⍴ takes a negation right operand.
        ⌿/⍀ take a range-level right operand so that ``f ⌿ 1…5`` works.
        When the right operand of ⌿/⍀ is a 2-tuple literal, the second
        element is the initial accumulator value.
        """
        # An operator may stand where the fold expects a function, so
        # `⧺⌿ v` says what a lambda repeating the operator would.  It is
        # one only when the fold glyph follows it directly; anywhere
        # else an operator needs its operands.
        if (self._check("OP") and self._cur().value in _FOLDABLE_OPS
                and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1].type == "OP"
                and self.tokens[self.pos + 1].value in _FOLD_OPS):
            op_tok = self._cur()
            self.pos += 1
            left = self._set_pos(OperatorRef(op_tok.value), op_tok)
        else:
            left = self._parse_negation()
        if self._check("OP") and self._cur().value == "\N{APL FUNCTIONAL SYMBOL RHO}":
            self.pos += 1
            self._skip_nl()
            right = self._parse_negation()
            return ReshapeExpr(left, right)
        if self._check("OP") and self._cur().value in (
                "\N{APL FUNCTIONAL SYMBOL SLASH BAR}",
                "\N{APL FUNCTIONAL SYMBOL BACKSLASH BAR}"):
            direction = "left" if self._cur().value == "\N{APL FUNCTIONAL SYMBOL SLASH BAR}" else "right"
            self.pos += 1
            self._skip_nl()
            right = self._parse_range_expr()
            if isinstance(right, TupleLit) and len(right.elements) == 2:
                return FoldExpr(direction, left, right.elements[0], right.elements[1])
            return FoldExpr(direction, left, right)
        return left

    def _parse_negation(self):
        """negation → '⁻' negation | power_expr

        Unary negation binds looser than ↑: ⁻2↑2 = ⁻(2↑2) = ⁻4.
        """
        if self._check("OP") and self._cur().value == "⁻":
            neg_tok = self._cur()
            self.pos += 1
            operand = self._parse_negation()
            return self._set_pos(UnaryOp("⁻", operand), neg_tok)
        return self._parse_power_expr()

    def _parse_power_expr(self):
        """power_expr → unary ('↑' negation)?  (right-associative)

        Right operand goes through negation to allow 2↑⁻3.
        """
        left = self._parse_unary()
        if self._check("OP") and self._cur().value == "\N{UPWARDS ARROW}":
            pow_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_negation()
            return self._set_binop_pos(BinOp("\N{UPWARDS ARROW}", left, right), left, right, pow_tok)
        return left

    def _parse_unary(self):
        """unary → ('~' | '¬' | 'not' | '√' | '∛' | '∜' | '⌈' | '⌊' | '@wrap') unary | primary

        `⌈` and `⌊` in front of an operand are the upper and lower case
        of text.  Between two operands they are the larger and the
        smaller of two numbers; which one is meant is settled by where
        the glyph is written, as it is for a minus sign.
        """
        if self._check("OP") and self._cur().value in _CASE_OPS:
            op_tok = self._cur()
            self.pos += 1
            operand = self._parse_unary()
            return self._set_pos(UnaryOp(op_tok.value, operand), op_tok)
        if self._check("OP") and self._cur().value == "~":
            op_tok = self._cur()
            self.pos += 1
            operand = self._parse_unary()
            return self._set_pos(UnaryOp("~", operand), op_tok)
        if self._check("OP") and self._cur().value == "\N{SQUARE ROOT}":
            op_tok = self._cur()
            self.pos += 1
            operand = self._parse_unary()
            return self._set_pos(UnaryOp("\N{SQUARE ROOT}", operand), op_tok)
        if self._check("OP") and self._cur().value == "\N{CUBE ROOT}":
            op_tok = self._cur()
            self.pos += 1
            operand = self._parse_unary()
            return self._set_pos(UnaryOp("\N{CUBE ROOT}", operand), op_tok)
        if self._check("OP") and self._cur().value == "\N{FOURTH ROOT}":
            op_tok = self._cur()
            self.pos += 1
            operand = self._parse_unary()
            return self._set_pos(UnaryOp("\N{FOURTH ROOT}", operand), op_tok)
        if self._check("OP") and self._cur().value == "¬":
            op_tok = self._cur()
            self.pos += 1
            operand = self._parse_unary()
            return self._set_pos(UnaryOp("¬", operand), op_tok)
        if self._check("NOT"):
            op_tok = self._cur()
            self._eat("NOT")
            operand = self._parse_unary()
            return self._set_pos(UnaryOp("not", operand), op_tok)
        if self._check("WRAP"):
            self._eat("WRAP")
            self._eat("PUNCT", "(")
            expr = self._parse_or_expr()
            self._skip_nl()
            self._eat("PUNCT", ")")
            return WrapExpr(expr)
        if self._check("ENUMERATE"):
            self._eat("ENUMERATE")
            self._eat("PUNCT", "(")
            expr = self._parse_or_expr()
            self._skip_nl()
            self._eat("PUNCT", ")")
            return EnumerateExpr(expr)
        if self._check("TYPEOF"):
            self._eat("TYPEOF")
            self._eat("PUNCT", "(")
            expr = self._parse_or_expr()
            self._skip_nl()
            self._eat("PUNCT", ")")
            node = TypeOfExpr(expr)
            return self._parse_postfix(node)
        if self._check("RESULTOF"):
            self._eat("RESULTOF")
            self._eat("PUNCT", "(")
            name_tok = self._eat("IDENT")
            self._skip_nl()
            self._eat("PUNCT", ")")
            node = ResultOfExpr(name_tok.value)
            return self._parse_postfix(node)
        if self._check("SIZEOF"):
            self._eat("SIZEOF")
            self._eat("PUNCT", "(")
            expr = self._parse_or_expr()
            self._skip_nl()
            self._eat("PUNCT", ")")
            node = SizeOfExpr(expr)
            return self._parse_postfix(node)
        if self._check("MIN", "MAX"):
            kind = "min" if self._check("MIN") else "max"
            self.pos += 1
            self._eat("PUNCT", "(")
            expr = self._parse_or_expr()
            self._skip_nl()
            self._eat("PUNCT", ")")
            return self._parse_postfix(LimitExpr(kind, expr))
        if self._check("DROPUNIT"):
            self._eat("DROPUNIT")
            self._eat("PUNCT", "(")
            expr = self._parse_or_expr()
            self._skip_nl()
            self._eat("PUNCT", ")")
            node = DropUnitExpr(expr)
            return self._parse_postfix(node)
        if self._check("UNITOF"):
            self._eat("UNITOF")
            self._eat("PUNCT", "(")
            expr = self._parse_or_expr()
            self._skip_nl()
            self._eat("PUNCT", ")")
            node = UnitOfExpr(expr)
            return self._parse_postfix(node)
        if self._check("OP") and self._cur().value == "\N{CURRENCY SIGN}":
            self.pos += 1
            unit_spec = self._parse_unit_spec()
            return UnitRefExpr(unit_spec)
        node = self._parse_primary()
        if self._check("OP") and self._cur().value == "\N{CURRENCY SIGN}":
            self.pos += 1
            unit_spec = self._parse_unit_spec()
            node = UnitExpr(node, unit_spec)
        if self._check("OP") and self._cur().value == "?":
            try_tok = self._cur()
            self.pos += 1
            node = self._set_pos(TryUnwrap(node), try_tok)
        return node

    def _parse_primary(self):
        """primary → atom (('.' ident | '[' expr ']')* | '(' args ')')

        An atom is a literal, parenthesized expression, array literal, some(...),
        new allocation, or an identifier. Dotted chains (obj.method) and subscript
        chains (arr[i]) are parsed as GetAttr/Subscript nodes built up from left
        to right in a single pass.
        """
        tok = self._cur()

        # Lambda expression: λparams |captures|: body
        if tok.type == "LAMBDA":
            return self._parse_lambda()

        # Literals.
        if tok.type == "INT":
            self.pos += 1
            return self._set_pos(IntLit(tok.value, tok.width or "int"), tok)

        if tok.type == "FLOAT":
            self.pos += 1
            value, width = tok.value
            return self._set_pos(FloatLit(value, width), tok)

        if tok.type == "CHAR":
            self.pos += 1
            # A member call may follow, as it may on a name: 'a'.ord()
            # reads as one thing and has nothing to be ambiguous with.
            return self._parse_postfix(
                self._set_pos(CharLit(tok.value), tok))

        if tok.type == "STR":
            self.pos += 1
            return self._parse_postfix(
                self._set_pos(StrLit(tok.value), tok))

        if tok.type == "NONE":
            self.pos += 1
            return self._set_pos(NoneLit(), tok)

        if tok.type == "TRUE":
            self.pos += 1
            return self._set_pos(BoolLit(True), tok)

        if tok.type == "FALSE":
            self.pos += 1
            return self._set_pos(BoolLit(False), tok)

        # Failed-result constructor ∄(...).
        if tok.type == "NOTEXISTS":
            self.pos += 1
            self._eat("PUNCT", "(")
            value = self._parse_or_expr()
            self._eat("PUNCT", ")")
            return self._set_pos(ExpErr(value), tok)

        # Optional some(...) constructor.
        if tok.type == "SOME":
            self.pos += 1
            self._eat("PUNCT", "(")
            value = self._parse_or_expr()
            self._eat("PUNCT", ")")
            return OptSome(value)

        # Array literal [...].
        if tok.type == "PUNCT" and tok.value == "[":
            self.pos += 1
            elements = []
            while True:
                self._skip_nl()
                if self._check("PUNCT") and self._cur().value == "]":
                    break
                expr = self._parse_or_expr()
                elements.append(expr)
                self._skip_nl()
                if not self._try_eat("PUNCT", ","):
                    break
            close = self._eat("PUNCT", "]")
            # The literal spans its brackets when both are on one line,
            # so a diagnostic can underline the whole of it.
            end = (close.end_col if close.line == tok.line
                   and close.end_col is not None else None)
            return set_pos(ArrayLit(elements), tok.line, tok.col, end)

        # Dynamic array allocation: new type[size].
        if tok.type == "IDENT" and tok.value == "new":
            self.pos += 1  # eat "new"
            type_tok = self._eat("IDENT")
            self._eat("PUNCT", "[")
            size_expr = self._parse_or_expr()
            self._skip_nl()
            self._eat("PUNCT", "]")
            return ArrayAlloc(type_tok.value, size_expr)

        # Parenthesized expression or tuple literal.
        if tok.type == "PUNCT" and tok.value == "(":
            self.pos += 1
            first = self._parse_or_expr()
            if self._check("PUNCT") and self._cur().value == ",":
                elements = [first]
                while self._try_eat("PUNCT", ","):
                    self._skip_nl()
                    if self._check("PUNCT") and self._cur().value == ")":
                        break
                    elements.append(self._parse_or_expr())
                self._skip_nl()
                self._eat("PUNCT", ")")
                return TupleLit(elements)
            self._skip_nl()
            self._eat("PUNCT", ")")
            return self._parse_postfix(first)

        # static_assert / static_assert_eq — special forms.
        if tok.type == "IDENT" and tok.value == "static_assert":
            self.pos += 1
            args = self._parse_call_args()
            return self._set_pos(StaticAssert(args), tok)

        if tok.type == "IDENT" and tok.value == "static_assert_eq":
            self.pos += 1
            args = self._parse_call_args()
            if len(args) != 2:
                raise ParseError("static_assert_eq requires exactly 2 arguments", tok)
            return self._set_pos(StaticAssertEq(args[0], args[1]), tok)

        # Identifier (possibly function call, possibly followed by dotted chain).
        if tok.type == "IDENT":
            self.pos += 1
            name = tok.value

            # Check for function call: name(...)
            if (self._cur().type == "PUNCT" and self._cur().value == "("):
                args = self._parse_call_args()
                node = self._set_pos(FuncCall(name, args), tok)
            elif self._check("PUNCT") and self._cur().value == "{" and self._is_struct_literal_start():
                node = self._set_pos(self._parse_struct_lit(name), tok)
            else:
                node = self._set_pos(VarRef(name), tok)

            # Chain attribute/method/subscript accesses in order:
            #   .ident → GetAttr
            #   [expr] → Subscript
            #   (args) → MethodCall (on previous node)
            while True:
                if self._check("PUNCT") and self._cur().value == ".":
                    dot_tok = self._cur()
                    self.pos += 1
                    attr_name = self._eat_member_name()
                    if self._check("PUNCT") and self._cur().value == "(":
                        args = self._parse_call_args()
                        node = self._set_pos(MethodCall(node, attr_name, args), dot_tok)
                    else:
                        node = self._set_pos(GetAttr(node, attr_name), dot_tok)
                elif self._check("PUNCT") and self._cur().value == "[":
                    bracket_tok = self._cur()
                    self.pos += 1
                    node = self._set_pos(self._parse_bracket_access(node), bracket_tok)
                elif self._check("PUNCT") and self._cur().value == "(":
                    call_tok = self._cur()
                    args = self._parse_call_args()
                    if isinstance(node, VarRef):
                        node = self._set_pos(FuncCall(node.name, args), tok)
                    else:
                        node = self._set_pos(MethodCall(node, "__call__", args), call_tok)
                else:
                    break

            return node

        raise ParseError(f"unexpected token: {self._tok_display(tok)}", tok)

    def _is_struct_literal_start(self) -> bool:
        """Check if { starts a struct literal (vs. a brace block)."""
        lookahead = self.pos + 1
        while (lookahead < len(self.tokens)
               and self.tokens[lookahead].type in ("NEWLINE", "INDENT", "DEDENT")):
            lookahead += 1
        if lookahead >= len(self.tokens):
            return False
        if (self.tokens[lookahead].type == "PUNCT"
                and self.tokens[lookahead].value == "}"):
            return True
        if (self.tokens[lookahead].type == "IDENT"
                and lookahead + 1 < len(self.tokens)
                and self.tokens[lookahead + 1].type == "PUNCT"
                and self.tokens[lookahead + 1].value == ":"):
            return True
        return False

    def _parse_struct_lit(self, name: str) -> StructLit:
        """Parse struct literal body: { field: expr, ... }."""
        self._eat("PUNCT", "{")
        field_inits: list[tuple[str, object]] = []
        while True:
            while not self._check("EOF") and self._cur().type in ("NEWLINE", "INDENT", "DEDENT"):
                self.pos += 1
            if self._check("PUNCT") and self._cur().value == "}":
                break
            field_name_tok = self._eat("IDENT")
            self._eat("PUNCT", ":")
            value_expr = self._parse_or_expr()
            field_inits.append((field_name_tok.value, value_expr))
            while not self._check("EOF") and self._cur().type in ("NEWLINE", "INDENT", "DEDENT"):
                self.pos += 1
            if not self._try_eat("PUNCT", ","):
                break
        while not self._check("EOF") and self._cur().type in ("NEWLINE", "INDENT", "DEDENT"):
            self.pos += 1
        self._eat("PUNCT", "}")
        return StructLit(name, field_inits)

    def _parse_bracket_access(self, node, bracket_tok=None):
        """Parse [expr, ...] after node — returns Subscript, SliceAccess, or MultiSlice.

        An entry may be empty, which is how an array type leaves a
        dimension open.  `i32[]` and `i32[,3]` are array types written
        where an expression is expected, so they parse here and are
        judged by whatever asked for them; a value has no such reading
        and says so.
        """
        def entry():
            if self._check("PUNCT") and self._cur().value in (",", "]"):
                return None
            return self._parse_or_expr()

        idx_expr = entry()
        indices = [idx_expr]
        while self._check("PUNCT") and self._cur().value == ",":
            self.pos += 1
            indices.append(entry())
        self._skip_nl()
        self._eat("PUNCT", "]")
        if any(i is None for i in indices):
            return Subscript(node, indices)
        has_range = any(isinstance(e, RangeExpr) for e in indices)
        if len(indices) == 1 and not has_range:
            return Subscript(node, indices)
        if len(indices) == 1 and has_range:
            return SliceAccess(node, idx_expr.start, idx_expr.end)
        if has_range:
            specs = []
            for e in indices:
                if isinstance(e, RangeExpr):
                    specs.append(("range", e.start, e.end))
                else:
                    specs.append(("index", e))
            return MultiSlice(node, specs)
        return Subscript(node, indices)

    def _eat_member_name(self) -> str:
        """Read the name after a `.`, which may spell a keyword.

        A member called `type` or `is` is a perfectly good name, and the
        position after a dot cannot be anything but a member, so there is
        nothing for a keyword to be ambiguous with here.
        """
        tok = self._cur()
        if tok.type == "IDENT" or (isinstance(tok.value, str)
                                   and KEYWORDS.get(tok.value) == tok.type):
            self.pos += 1
            return tok.value
        raise ParseError(
            f"expected a member name after '.', got {self._tok_display(tok)}",
            tok)

    def _parse_postfix(self, node):
        """Chain .attr, [idx], and (args) postfix operators onto node."""
        while True:
            if self._check("PUNCT") and self._cur().value == ".":
                dot_tok = self._cur()
                self.pos += 1
                attr_name = self._eat_member_name()
                if self._check("PUNCT") and self._cur().value == "(":
                    args = self._parse_call_args()
                    node = self._set_pos(MethodCall(node, attr_name, args),
                                         dot_tok)
                else:
                    node = self._set_pos(GetAttr(node, attr_name), dot_tok)
            elif self._check("PUNCT") and self._cur().value == "[":
                self.pos += 1
                node = self._parse_bracket_access(node)
            elif self._check("PUNCT") and self._cur().value == "(":
                args = self._parse_call_args()
                node = MethodCall(node, "__call__", args)
            else:
                break
        if self._check("OP") and self._cur().value == "?":
            try_tok = self._cur()
            self.pos += 1
            node = self._set_pos(TryUnwrap(node), try_tok)
        return node

    def _parse_call_args(self):
        """Parse function/method call arguments: ( arg, arg, ... )."""
        self._eat("PUNCT", "(")
        args = []
        while True:
            while self._try_eat("NEWLINE"):
                pass
            if self._check("PUNCT") and self._cur().value == ")":
                break
            if (self._check("OP") and self._cur().value == "&"
                    and self.pos + 1 < len(self.tokens)
                    and self.tokens[self.pos + 1].type == "IDENT"):
                ref_tok = self._cur()
                self.pos += 1
                name_tok = self._eat("IDENT")
                arg = self._set_pos(RefExpr(name_tok.value), ref_tok)
            else:
                arg = self._parse_or_expr()
            args.append(arg)
            while self._try_eat("NEWLINE"):
                pass
            if not self._try_eat("PUNCT", ","):
                break
        self._eat("PUNCT", ")")
        return args
