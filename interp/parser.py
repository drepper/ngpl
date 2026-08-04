"""Recursive descent parser for the newlang language.

Builds an Abstract Syntax Tree (AST) from a token stream produced by the lexer.
Supports function definitions, variable definitions, if/while/control flow,
expressions with operator precedence, and function/method calls.
"""

from interp.ast import (
    IntLit, StrLit, BoolLit, NoneLit, VarRef, BinOp, UnaryOp,
    IfStmt, WhileStmt, ReturnStmt, FuncDef, VarDef, ExprStmt,
    FuncCall, MethodCall, OptSome, GetAttr,
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
            self._try_eat("NEWLINE")
            definition = self._parse_definition()
            if definition is not None:
                definitions.append(definition)
        return definitions

    def _parse_definition(self):
        """Parse a single top-level definition (function or variable)."""
        is_start = False
        if self._check("START"):
            self._eat("START")
            is_start = True
            self._try_eat("NEWLINE")

        if self._check("FN"):
            return self._parse_function_def(is_start)
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
        if not (self._cur().type == "PUNCT" and self._cur().value == ")"):
            while True:
                param_name_tok = self._eat("IDENT")
                param_type = None
                if self._try_eat("PUNCT", ":"):
                    type_tok = self._eat("IDENT")
                    param_type = type_tok.value
                params.append((param_name_tok.value, param_type))
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
        """Parse: var name [:type] = expr"""
        keyword = self._cur().value
        self._eat(keyword.upper())
        name_tok = self._eat("IDENT")

        type_annotation = None
        if self._try_eat("PUNCT", ":"):
            type_annotation = self._eat("IDENT").value

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
        if self._check("EOF"):
            return None

        if self._check("VAR", "LET"):
            return self._parse_var_def()

        if self._check("IF"):
            return self._parse_if_stmt()

        if self._check("WHILE"):
            return self._parse_while_stmt()

        if self._check("RETURN"):
            return self._parse_return_stmt()

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

    def _parse_or_expr(self):
        """or_expr → and_expr ('or' and_expr)*"""
        left = self._parse_and_expr()
        while self._try_eat("OR"):
            right = self._parse_and_expr()
            left = BinOp("or", left, right)
        return left

    def _parse_and_expr(self):
        """and_expr → cmp_expr ('and' cmp_expr)*"""
        left = self._parse_cmp_expr()
        while self._try_eat("AND"):
            right = self._parse_cmp_expr()
            left = BinOp("and", left, right)
        return left

    def _parse_cmp_expr(self):
        """cmp_expr → add_expr (('==' | '!=' | '<' | '>' | '<=' | '>=') add_expr)*"""
        left = self._parse_add_expr()
        while self._check("OP") and self._cur().value in ("==", "!=", "<", ">", "<=", ">="):
            op_tok = self._cur()
            self.pos += 1
            right = self._parse_add_expr()
            left = BinOp(op_tok.value, left, right)
        return left

    def _parse_add_expr(self):
        """add_expr → mul_expr (('+' | '-') mul_expr)*"""
        left = self._parse_mul_expr()
        while self._check("OP") and self._cur().value in ("+", "-"):
            op_tok = self._cur()
            self.pos += 1
            right = self._parse_mul_expr()
            left = BinOp(op_tok.value, left, right)
        return left

    def _parse_mul_expr(self):
        """mul_expr → unary (('*' | '/') unary)*"""
        left = self._parse_unary()
        while self._check("OP") and self._cur().value in ("*", "/"):
            op_tok = self._cur()
            self.pos += 1
            right = self._parse_unary()
            left = BinOp(op_tok.value, left, right)
        return left

    def _parse_unary(self):
        """unary → ('-' | 'not') unary | primary"""
        if self._check("OP") and self._cur().value == "-":
            self.pos += 1
            operand = self._parse_unary()
            return UnaryOp("-", operand)
        if self._check("NOT"):
            self._eat("NOT")
            operand = self._parse_unary()
            return UnaryOp("not", operand)
        return self._parse_primary()

    def _parse_primary(self):
        """primary → atom ('.' ident)*

        An atom is a literal, parenthesized expression, some(...), or an identifier.
        If the atom starts with an identifier followed by '(', it is a function call.
        Dotted chains (obj.method, fs.cwd, get_stdout().fd) are parsed as a sequence
        of GetAttr nodes built up from left to right.
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

        # Parenthesized expression.
        if tok.type == "PUNCT" and tok.value == "(":
            self.pos += 1
            expr = self._parse_or_expr()
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

            # Chain attribute/method accesses: .ident or .ident(...)
            while (self._cur().type == "PUNCT" and self._cur().value == "."):
                self.pos += 1  # eat the "."
                attr_tok = self._eat("IDENT")
                attr_name = attr_tok.value
                if (self._cur().type == "PUNCT" and self._cur().value == "("):
                    args = self._parse_call_args()
                    node = MethodCall(node, attr_name, args)
                else:
                    node = GetAttr(node, attr_name)

            return node

        raise ParseError(f"unexpected token: {tok.type} {tok.value!r}", tok)

    def _parse_call_args(self):
        """Parse function/method call arguments: ( arg, arg, ... )."""
        self._eat("PUNCT", "(")
        args = []
        if not (self._cur().type == "PUNCT" and self._cur().value == ")"):
            while True:
                arg = self._parse_or_expr()
                args.append(arg)
                if not self._try_eat("PUNCT", ","):
                    break
        self._eat("PUNCT", ")")
        return args
