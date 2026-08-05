"""Recursive descent parser for the newlang language.

Builds an Abstract Syntax Tree (AST) from a token stream produced by the lexer.
Supports function definitions, variable definitions, if/while/control flow,
expressions with operator precedence, and function/method calls.
"""

from interp.ast import (
    IntLit, StrLit, BoolLit, NoneLit, VarRef, BinOp, UnaryOp,
    IfStmt, WhileStmt, ReturnStmt, FuncDef, VarDef, ExprStmt,
    FuncCall, MethodCall, OptSome, GetAttr,
    ArrayLit, Subscript, SliceAccess, ArrayAlloc,
)
from interp.lexer import Token


class ParseError(Exception):
    """Raised when the parser encounters invalid input."""

    def __init__(self, message, token=None):
        if token:
            msg = f"Line {token.line}, col {token.col}: {message}"
        else:
            msg = message
        super().__init__(msg)


class Parser:
    """Recursive descent parser."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    # ------------------------------------------------------------------
    # Token access helpers
    # ------------------------------------------------------------------

    def _cur(self):
        """Return the current token without consuming it."""
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return self.tokens[-1]  # EOF

    def _eat(self, type_, value=None):
        """Consume and return the current token if it matches; else error."""
        tok = self._cur()
        if tok.type != type_:
            raise ParseError(f"expected {type_}{' ' + repr(value) if value else ''}, got {tok.type}", tok)
        if value is not None and tok.value != value:
            raise ParseError(f"expected {value!r}, got {tok.value!r}", tok)
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
            # Skip all consecutive newlines (including multiple blank lines).
            while self._try_eat("NEWLINE"):
                pass
            definition = self._parse_definition()
            if definition is not None:
                definitions.append(definition)
        return definitions

    def _parse_definition(self):
        """Parse a single top-level definition (function, const, or variable)."""
        is_start = False
        if self._check("START"):
            self._eat("START")
            is_start = True
            self._try_eat("NEWLINE")

        if self._check("FN"):
            return self._parse_function_def(is_start)
        elif self._check("CONST"):
            self._eat("CONST")
            name_tok = self._eat("IDENT")
            type_ann = None
            if self._try_eat("PUNCT", ":"):
                if self._check("IDENT"):
                    type_ann = self._eat("IDENT").value
            self._eat("PUNCT", "=")
            init_expr = self._parse_or_expr()
            self._try_eat("PUNCT", ";")
            return ("const_assign", name_tok.value, type_ann, init_expr)
        elif self._check("VAR", "LET"):
            return self._parse_var_def()
        elif self._check("EOF"):
            return None  # end of file reached cleanly
        else:
            raise ParseError(f"expected function or variable definition, got {self._cur().type}")

    def _parse_function_def(self, is_start):
        """Parse: fn name(params) -> ret_type? { stmts }"""
        self._eat("FN")
        name_tok = self._eat("IDENT")
        name = name_tok.value

        self._eat("PUNCT", "(")
        params = []
        while True:
            # Skip any leading newlines before each parameter (for multi-line lists).
            while self._try_eat("NEWLINE"):
                pass
            if self._check("PUNCT") and self._cur().value == ")":
                break
            param_name_tok = self._eat("IDENT")
            param_type = None
            if self._try_eat("PUNCT", ":"):
                type_tok = self._eat("IDENT")
                param_type = type_tok.value
            params.append((param_name_tok.value, param_type))
            # Skip a single newline after comma (multi-line parameter lists).
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

        body = self._parse_block()
        return FuncDef(name, params, ret_type, body, is_start)

    def _parse_var_def(self):
        """Parse: var name := expr  |  var name : type = expr  |  var name : type[size] = init"""
        keyword = self._cur().value
        self._eat(keyword.upper())
        name_tok = self._eat("IDENT")

        type_annotation = None
        if self._try_eat("PUNCT", ":"):
            if self._check("IDENT"):
                type_annotation = self._eat("IDENT").value
                if self._check("PUNCT") and self._cur().value == "[":
                    self.pos += 1
                    size_expr = self._parse_or_expr()
                    self._eat("PUNCT", "]")
                    self._eat("PUNCT", "=")
                    init_expr = self._parse_or_expr()
                    self._try_eat("PUNCT", ";")
                    return VarDef(name_tok.value, type_annotation,
                                  ArrayAlloc(type_annotation, size_expr, init_expr))

        self._eat("PUNCT", "=")
        init_expr = self._parse_or_expr()
        self._try_eat("PUNCT", ";")

        return VarDef(name_tok.value, type_annotation, init_expr)

    def _parse_block(self):
        """Parse a brace-delimited block: { stmts }."""
        self._eat("PUNCT", "{")
        stmts = []
        while True:
            # Skip any trailing newlines before checking for closing brace.
            while not self._check("EOF") and self._cur().type == "NEWLINE":
                self.pos += 1
            if (self._check("EOF") or
                    (self._cur().type == "PUNCT" and self._cur().value == "}")):
                break
            stmt = self._parse_statement()
            if stmt is not None:
                stmts.append(stmt)
        self._eat("PUNCT", "}")
        return stmts

    # ------------------------------------------------------------------
    # Statement parsing
    # ------------------------------------------------------------------

    def _parse_statement(self):
        """Parse a single statement."""
        # Skip leading newlines (e.g. blank lines between statements).
        while self._try_eat("NEWLINE"):
            pass

        if self._check("EOF"):
            return None

        if self._check("VAR", "LET"):
            return self._parse_var_def()

        if self._check("CONST"):
            self._eat("CONST")
            name_tok = self._eat("IDENT")
            type_ann = None
            if self._try_eat("PUNCT", ":"):
                if self._check("IDENT"):
                    type_ann = self._eat("IDENT").value
            self._eat("PUNCT", "=")
            init_expr = self._parse_or_expr()
            self._try_eat("PUNCT", ";")
            return ("const_assign", name_tok.value, type_ann, init_expr)

        if self._check("IF"):
            return self._parse_if_stmt()

        if self._check("WHILE"):
            return self._parse_while_stmt()

        if self._check("RETURN"):
            return self._parse_return_stmt()

        # General assignment: LHS ← RHS  |  LHS = RHS.
        # LHS can be an identifier or subscript chain (arr[i]).
        # Peek ahead past brackets/newlines to find a top-level ← or = on this line.
        if self._check("IDENT") or (self._check("PUNCT") and self._cur().value == "("):
            saved_pos = self.pos
            bracket_depth = 0
            found_assign_op = None  # "←" or "="
            while saved_pos < len(self.tokens):
                t = self.tokens[saved_pos]
                if t.type == "NEWLINE" or t.type == ";":
                    break
                if t.type == "PUNCT":
                    if t.value == "[": bracket_depth += 1
                    elif t.value == "]": bracket_depth -= 1
                if t.type == "OP" and t.value == "←" and bracket_depth == 0:
                    found_assign_op = "←"
                    break
                saved_pos += 1

            # Also check for ASCII '=' at top level (not inside brackets).
            if not found_assign_op:
                bp2 = self.pos
                bd2 = 0
                while bp2 < len(self.tokens):
                    t2 = self.tokens[bp2]
                    if t2.type == "NEWLINE" or t2.type == ";":
                        break
                    if t2.type == "PUNCT":
                        if t2.value == "[": bd2 += 1
                        elif t2.value == "]": bd2 -= 1
                    if t2.type == "PUNCT" and t2.value == "=" and bd2 == 0:
                        # Make sure it's not part of a comparison (==).
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
        """Parse: if cond { stmts } (elif cond { stmts })* (else { stmts })?"""
        self._eat("IF")
        cond = self._parse_or_expr()
        cons_body = self._parse_block()

        alt = None
        while True:
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
        """Parse: while cond { stmts }"""
        self._eat("WHILE")
        cond = self._parse_or_expr()
        body = self._parse_block()
        return WhileStmt(cond, body)

    def _parse_return_stmt(self):
        """Parse: return [expr]"""
        self._eat("RETURN")
        value = None
        if not self._check("EOF") and not (self._cur().type == "PUNCT" and self._cur().value == "}") and not self._cur().type == "NEWLINE":
            value = self._parse_or_expr()
        self._try_eat("PUNCT", ";")
        return ReturnStmt(value)

    # ------------------------------------------------------------------
    # Expression parsing (precedence climbing)
    # ------------------------------------------------------------------

    def _skip_nl(self):
        """Skip any NEWLINE tokens (for multi-line expressions)."""
        while self._check("NEWLINE"):
            self.pos += 1

    def _parse_or_expr(self):
        """or_expr → and_expr ('or' and_expr)*"""
        left = self._parse_and_expr()
        while True:
            self._skip_nl()
            if not self._try_eat("OR"):
                break
            self._skip_nl()
            right = self._parse_and_expr()
            left = BinOp("or", left, right)
        return left

    def _parse_and_expr(self):
        """and_expr → cmp_expr ('and' cmp_expr)*"""
        left = self._parse_cmp_expr()
        while True:
            self._skip_nl()
            if not self._try_eat("AND"):
                break
            self._skip_nl()
            right = self._parse_cmp_expr()
            left = BinOp("and", left, right)
        return left

    def _parse_cmp_expr(self):
        """cmp_expr → shift_expr (('==' | '!=' | '<' | '>' | '<=' | '>=') shift_expr)*"""
        left = self._parse_shift_expr()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value in ("==", "!=", "<", ">", "<=", ">=")):
                break
            op_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_shift_expr()
            left = BinOp(op_tok.value, left, right)
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
            left = BinOp(op_tok.value, left, right)
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
            left = BinOp("|", left, right)
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
            left = BinOp("^", left, right)
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
            left = BinOp("&", left, right)
        return left

    def _parse_add_expr(self):
        """add_expr → mul_expr (('+' | '-') mul_expr)*"""
        left = self._parse_mul_expr()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value in ("+", "-")):
                break
            op_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_mul_expr()
            left = BinOp(op_tok.value, left, right)
        return left

    def _parse_mul_expr(self):
        """mul_expr → unary (('*' | '/' | '%') unary)*"""
        left = self._parse_unary()
        while True:
            self._skip_nl()
            if not (self._check("OP") and self._cur().value in ("*", "/", "%")):
                break
            op_tok = self._cur()
            self.pos += 1
            self._skip_nl()
            right = self._parse_unary()
            left = BinOp(op_tok.value, left, right)
        return left

    def _parse_unary(self):
        """unary → ('-' | '~' | 'not') unary | primary"""
        if self._check("OP") and self._cur().value == "-":
            self.pos += 1
            operand = self._parse_unary()
            return UnaryOp("-", operand)
        if self._check("OP") and self._cur().value == "~":
            self.pos += 1
            operand = self._parse_unary()
            return UnaryOp("~", operand)
        if self._check("NOT"):
            self._eat("NOT")
            operand = self._parse_unary()
            return UnaryOp("not", operand)
        return self._parse_primary()

    def _parse_primary(self):
        """primary → atom (('.' ident | '[' expr ']')* | '(' args ')')

        An atom is a literal, parenthesized expression, array literal, some(...),
        new allocation, or an identifier. Dotted chains (obj.method) and subscript
        chains (arr[i]) are parsed as GetAttr/Subscript nodes built up from left
        to right in a single pass.
        """
        tok = self._cur()

        # Literals.
        if tok.type == "INT":
            self.pos += 1
            return IntLit(tok.value)

        if tok.type == "STR":
            self.pos += 1
            return StrLit(tok.value)

        if tok.type == "NONE":
            self.pos += 1
            return NoneLit()

        if tok.type == "TRUE":
            self.pos += 1
            return BoolLit(True)

        if tok.type == "FALSE":
            self.pos += 1
            return BoolLit(False)

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

        # Parenthesized expression.
        if tok.type == "PUNCT" and tok.value == "(":
            self.pos += 1
            expr = self._parse_or_expr()
            self._skip_nl()
            self._eat("PUNCT", ")")
            return expr

        # Identifier (possibly function call, possibly followed by dotted chain).
        if tok.type == "IDENT":
            self.pos += 1
            name = tok.value

            # Check for function call: name(...)
            if (self._cur().type == "PUNCT" and self._cur().value == "("):
                args = self._parse_call_args()
                node = FuncCall(name, args)
            else:
                node = VarRef(name)

            # Chain attribute/method/subscript accesses in order:
            #   .ident → GetAttr
            #   [expr] → Subscript
            #   (args) → MethodCall (on previous node)
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
                    start_expr = self._parse_or_expr()
                    if self._check("PUNCT") and self._cur().value == "…":
                        self.pos += 1
                        end_expr = self._parse_or_expr()
                        self._skip_nl()
                        self._eat("PUNCT", "]")
                        node = SliceAccess(node, start_expr, end_expr)
                    else:
                        self._skip_nl()
                        self._eat("PUNCT", "]")
                        node = Subscript(node, start_expr)
                elif self._check("PUNCT") and self._cur().value == "(":
                    args = self._parse_call_args()
                    if isinstance(node, VarRef):
                        node = FuncCall(node.name, args)
                    else:
                        # Method call on any previous expression.
                        node = MethodCall(node, "__call__", args)
                else:
                    break

            return node

        raise ParseError(f"unexpected token: {tok.type} {tok.value!r}", tok)

    def _parse_call_args(self):
        """Parse function/method call arguments: ( arg, arg, ... )."""
        self._eat("PUNCT", "(")
        args = []
        while True:
            # Skip leading newlines (multi-line argument lists).
            while self._try_eat("NEWLINE"):
                pass
            if self._check("PUNCT") and self._cur().value == ")":
                break
            arg = self._parse_or_expr()
            args.append(arg)
            # Skip newlines after comma.
            while self._try_eat("NEWLINE"):
                pass
            if not self._try_eat("PUNCT", ","):
                break
        self._eat("PUNCT", ")")
        return args
