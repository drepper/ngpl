"""Recursive descent parser for the NGPL language.

Builds an Abstract Syntax Tree (AST) from a token stream produced by the lexer.
Supports function definitions, variable definitions, if/while/control flow,
expressions with operator precedence, and function/method calls.

Blocks can use brace-delimited { ... } or layout-driven scoping with : and
indentation (INDENT/DEDENT tokens).
"""

from interp.ast import (
    IntLit, FloatLit, StrLit, BoolLit, NoneLit, VarRef, RefExpr, BinOp, UnaryOp,
    IfStmt, WhileStmt, ReturnStmt, FuncDef, VarDef, ExprStmt,
    FuncCall, MethodCall, OptSome, GetAttr,
    ArrayLit, Subscript, SliceAccess, MultiSlice, ArrayAlloc, TryUnwrap,
    RangeExpr, ForEachStmt, ExpectStmt, WrapExpr, EnumDef,
    LambdaExpr, ReshapeExpr, TupleLit, CatchStmt, EnumerateExpr,
    StaticAssert, StaticAssertEq, TypeOfExpr, ResultOfExpr, SizeOfExpr, FoldExpr,
    UnitExpr, UnitDef, UnitName, UnitBinOp, UnitSqrt, UnitLit,
    UnitOfExpr, UnitRefExpr,
    set_pos,
)
from interp.lexer import Token, KEYWORDS


class ParseError(Exception):
    """Raised when the parser encounters invalid input."""

    def __init__(self, message, token=None):
        self.raw_message = message
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

    def _parse_definition(self):
        """Parse a single top-level definition (function, const, enum, or variable)."""
        is_start = False
        is_test = False
        is_flag = False
        is_replaceable = False
        is_impure = False
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

        if self._check("ENUM"):
            return self._parse_enum_def(is_flag)

        if self._check("UNIT"):
            return self._parse_unit_def()

        if self._check("FN"):
            return self._parse_function_def(is_start, is_test, test_refs, expect_annotations,
                                            is_replaceable, is_impure)
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
                            is_impure: bool = False):
        """Parse: fn name '(' [params] ')' ('->' ret_type)? block

        The parameter list is enclosed in parentheses.  An empty parameter
        list is written as ``()``.

        When @expect annotations are present, parse errors in the body are
        captured instead of propagated — the FuncDef stores the error message
        so main.py can match it against expected patterns.
        """
        self._eat("FN")
        name_tok = self._eat("IDENT")
        name = name_tok.value

        params = []
        param_units: dict[str, object] = {}
        param_refs: set[str] = set()
        param_muts: set[str] = set()
        pack_param: tuple[str, str | None] | None = None
        self._eat("PUNCT", "(")
        while not (self._check("PUNCT") and self._cur().value == ")"):
            while self._try_eat("NEWLINE"):
                pass
            if self._check("PUNCT") and self._cur().value == ")":
                break
            if not self._check("IDENT"):
                break
            param_name_tok = self._eat("IDENT")
            is_pack = self._try_eat("PUNCT", "\N{HORIZONTAL ELLIPSIS}")
            param_unit = None
            if self._check("OP") and self._cur().value == "\N{CURRENCY SIGN}":
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
                if next_is_type or next_is_ref or next_is_mut:
                    self._eat("PUNCT", ":")
                    if self._check("OP") and self._cur().value == "&":
                        self.pos += 1
                        is_ref = True
                    if self._try_eat("MUT"):
                        is_mut = True
                    type_tok = self._eat("IDENT")
                    param_type = type_tok.value
                if self._check("PUNCT") and self._cur().value == "[":
                    self.pos += 1
                    if self._check("PUNCT") and self._cur().value == "]":
                        self.pos += 1
                        param_type += "[]"
                    elif self._check("INT"):
                        size_tok = self._eat("INT")
                        self._eat("PUNCT", "]")
                        param_type += f"[{size_tok.value}]"
                    else:
                        self._eat("PUNCT", "]")
                        param_type += "[]"
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

        ret_type = None
        if self._try_eat("OP", "->"):
            if self._check("IDENT", "NONE", "OPT"):
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

        if expect_annotations:
            try:
                body = self._parse_block()
            except ParseError as e:
                body = []
                fdef = FuncDef(name, params, ret_type, body, is_start, is_test,
                               test_refs, expect_annotations, is_replaceable,
                               pack_param, param_units, is_impure,
                               param_refs=param_refs,
                               param_muts=param_muts)
                fdef._parse_error = str(e)
                self._skip_to_next_definition()
                return fdef
        else:
            body = self._parse_block()
        return FuncDef(name, params, ret_type, body, is_start, is_test,
                       test_refs, expect_annotations, is_replaceable,
                       pack_param, param_units, is_impure,
                       param_refs=param_refs,
                       param_muts=param_muts)

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
        self._eat("ENUM")
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
        return EnumDef(name, underlying_type, members, is_flag)

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

    def _parse_var_def(self):
        """Parse: let name [¤unit] := expr  |  let name [¤unit] : [mut] type = expr  |  let name : mut type[size] = init"""
        kw_tok = self._cur()
        self._eat("LET")
        keyword = "let"
        name_tok = self._eat("IDENT")

        unit_spec = None
        if self._check("OP") and self._cur().value == "\N{CURRENCY SIGN}":
            self.pos += 1
            unit_spec = self._parse_unit_spec()

        type_annotation = None
        is_const = True
        has_colon = self._try_eat("PUNCT", ":")
        if has_colon:
            if self._try_eat("MUT"):
                is_const = False
            if self._check("IDENT"):
                type_annotation = self._eat("IDENT").value
                if self._check("PUNCT") and self._cur().value == "[":
                    self.pos += 1
                    if self._check("PUNCT") and self._cur().value == "]":
                        self.pos += 1
                        type_annotation += "[]"
                    else:
                        size_expr = self._parse_or_expr()
                        self._eat("PUNCT", "]")
                        self._eat("PUNCT", "=")
                        init_expr = self._parse_or_expr()
                        self._try_eat("PUNCT", ";")
                        return self._set_pos(VarDef(name_tok.value, type_annotation,
                                      ArrayAlloc(type_annotation, size_expr, init_expr),
                                  is_const, unit_spec=unit_spec), kw_tok)

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

    def _parse_unit_def(self):
        """Parse: unit name [= formula]"""
        self._eat("UNIT")
        name_tok = self._eat("IDENT")
        formula = None
        if self._try_eat("PUNCT", "="):
            formula = self._parse_unit_formula()
        self._try_eat("PUNCT", ";")
        return UnitDef(name_tok.value, formula)

    def _parse_unit_spec(self):
        """Parse a unit specification after ¤ (no numeric literals)."""
        left = self._parse_unit_atom()
        while self._check("OP") and self._cur().value in ("*", "/"):
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
        while self._check("OP") and self._cur().value in ("*", "/"):
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

        if self._check("CATCH"):
            return self._parse_catch_stmt()

        if self._check("RETURN"):
            return self._parse_return_stmt()

        # General assignment: LHS ← RHS  |  LHS = RHS.
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

            if not found_assign_op:
                bp2 = self.pos
                bd2 = 0
                while bp2 < len(self.tokens):
                    t2 = self.tokens[bp2]
                    if t2.type in ("NEWLINE", "INDENT", "DEDENT") or (t2.type == "PUNCT" and t2.value == ";"):
                        break
                    if t2.type == "PUNCT":
                        if t2.value == "[": bd2 += 1
                        elif t2.value == "]": bd2 -= 1
                    if t2.type == "PUNCT" and t2.value == "=" and bd2 == 0:
                        if bp2 + 1 < len(self.tokens) and \
                           self.tokens[bp2 + 1].type == "PUNCT" and \
                           self.tokens[bp2 + 1].value == "=":
                            pass  # skip ==
                        else:
                            found_assign_op = "="
                            break
                    bp2 += 1

            if found_assign_op:
                lhs = self._parse_or_expr()
                if found_assign_op == "←":
                    self._eat("OP", "←")
                else:
                    self._eat("PUNCT", "=")
                rhs = self._parse_or_expr()
                self._try_eat("PUNCT", ";")
                return ("assign_stmt", lhs, rhs)

        expr = self._parse_or_expr()
        self._try_eat("PUNCT", ";")
        return ExprStmt(expr)

    def _parse_if_stmt(self):
        """Parse: if expr block (elif expr block)* (else block)?"""
        self._eat("IF")
        cond = self._parse_or_expr()
        cons_body = self._parse_block()

        alt = None
        while True:
            self._skip_nl()
            if self._check("ELIF"):
                self._eat("ELIF")
                elif_cond = self._parse_or_expr()
                elif_body = self._parse_block()
                if alt is None:
                    alt = (elif_cond, elif_body)
                else:
                    alt = (elif_cond, elif_body, alt)
            elif self._check("ELSE"):
                self._eat("ELSE")
                else_body = self._parse_block()
                if alt is None:
                    alt = (None, else_body)
                else:
                    alt = (None, else_body, alt)
            else:
                break

        return IfStmt(cond, cons_body, alt)

    def _parse_while_stmt(self):
        """Parse: while expr block"""
        self._eat("WHILE")
        cond = self._parse_or_expr()
        body = self._parse_block()
        return WhileStmt(cond, body)

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
            iterables.append(self._parse_or_expr())
            if not self._try_eat("PUNCT", ","):
                break
        body = self._parse_block()
        return ForEachStmt(vars_list, iterables, body, is_comptime)

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
        self._eat("LAMBDA")
        params: list[tuple[str, str]] = []
        while self._check("IDENT"):
            saved = self.pos
            name = self._eat("IDENT").value
            if not (self._check("PUNCT") and self._cur().value == ":" and
                    self.pos + 1 < len(self.tokens) and
                    self.tokens[self.pos + 1].type == "IDENT"):
                raise ParseError(
                    f"lambda parameter '{name}' requires a type annotation", self._cur())
            self._eat("PUNCT", ":")
            ptype = self._eat("IDENT").value
            if self._check("PUNCT") and self._cur().value == "[":
                self.pos += 1
                self._eat("PUNCT", "]")
                ptype += "[]"
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
        return LambdaExpr(params, captures, ret_type, body)

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

    def _parse_cmp_expr(self):
        """cmp_expr → range_expr (('==' | '!=' | '<' | '>' | '<=' | '>=') range_expr)*"""
        left = self._parse_range_expr()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value in ("==", "!=", "<", ">", "<=", ">=")):
                break
            op_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_range_expr()
            left = self._set_binop_pos(BinOp(op_tok.value, left, right), left, right, op_tok)
        return left

    def _parse_range_expr(self):
        """range_expr → shift_expr ('…' shift_expr ('…' shift_expr)?)?"""
        left = self._parse_shift_expr()
        if self._check("PUNCT") and self._cur().value == "…":
            self.pos += 1
            second = self._parse_shift_expr()
            if self._check("PUNCT") and self._cur().value == "…":
                self.pos += 1
                end = self._parse_shift_expr()
                return RangeExpr(left, end, step=second)
            return RangeExpr(left, second)
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
        """add_expr → concat_expr (('+' | '-') concat_expr)*"""
        left = self._parse_concat_expr()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value in ("+", "-")):
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
        """mul_expr → reshape (('*' | '/' | '%') reshape)*"""
        left = self._parse_reshape_expr()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value in ("*", "/", "%")):
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
        """unary → ('~' | '¬' | 'not' | '√' | '∛' | '∜' | '@wrap') unary | primary"""
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
            self.pos += 1
            node = TryUnwrap(node)
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
            return self._set_pos(IntLit(tok.value), tok)

        if tok.type == "FLOAT":
            self.pos += 1
            value, width = tok.value
            return self._set_pos(FloatLit(value, width), tok)

        if tok.type == "STR":
            self.pos += 1
            return self._set_pos(StrLit(tok.value), tok)

        if tok.type == "NONE":
            self.pos += 1
            return self._set_pos(NoneLit(), tok)

        if tok.type == "TRUE":
            self.pos += 1
            return self._set_pos(BoolLit(True), tok)

        if tok.type == "FALSE":
            self.pos += 1
            return self._set_pos(BoolLit(False), tok)

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
            self._eat("PUNCT", "]")
            return ArrayLit(elements)

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
            return StaticAssert(args)

        if tok.type == "IDENT" and tok.value == "static_assert_eq":
            self.pos += 1
            args = self._parse_call_args()
            if len(args) != 2:
                raise ParseError("static_assert_eq requires exactly 2 arguments", tok)
            return StaticAssertEq(args[0], args[1])

        # Identifier (possibly function call, possibly followed by dotted chain).
        if tok.type == "IDENT":
            self.pos += 1
            name = tok.value

            # Check for function call: name(...)
            if (self._cur().type == "PUNCT" and self._cur().value == "("):
                args = self._parse_call_args()
                node = self._set_pos(FuncCall(name, args), tok)
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
                    attr_tok = self._eat("IDENT")
                    attr_name = attr_tok.value
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

    def _parse_bracket_access(self, node, bracket_tok=None):
        """Parse [expr, ...] after node — returns Subscript, SliceAccess, or MultiSlice."""
        idx_expr = self._parse_or_expr()
        indices = [idx_expr]
        while self._check("PUNCT") and self._cur().value == ",":
            self.pos += 1
            indices.append(self._parse_or_expr())
        self._skip_nl()
        self._eat("PUNCT", "]")
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

    def _parse_postfix(self, node):
        """Chain .attr, [idx], and (args) postfix operators onto node."""
        while True:
            if self._check("PUNCT") and self._cur().value == ".":
                self.pos += 1
                attr_tok = self._eat("IDENT")
                attr_name = attr_tok.value
                if self._check("PUNCT") and self._cur().value == "(":
                    args = self._parse_call_args()
                    node = MethodCall(node, attr_name, args)
                else:
                    node = GetAttr(node, attr_name)
            elif self._check("PUNCT") and self._cur().value == "[":
                self.pos += 1
                node = self._parse_bracket_access(node)
            elif self._check("PUNCT") and self._cur().value == "(":
                args = self._parse_call_args()
                node = MethodCall(node, "__call__", args)
            else:
                break
        if self._check("OP") and self._cur().value == "?":
            self.pos += 1
            node = TryUnwrap(node)
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
