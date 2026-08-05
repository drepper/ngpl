"""Lexical analyzer for the newlang language.

Scans source text (UTF-8) and produces a stream of typed tokens.
Handles identifiers, keywords, integer/string literals, operators,
and punctuation. Skips comments and whitespace.
"""

import re


class Token:
    """A single lexical token."""

    __slots__ = ("type", "value", "line", "col")

    def __init__(self, type_, value, line, col):
        self.type = type_
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self):
        return f"Token({self.type}, {self.value!r}, @{self.line}:{self.col})"


# Keywords: maps keyword string to token type.
KEYWORDS = {
    "fn": "FN",
    "var": "VAR",
    "if": "IF",
    "else": "ELSE",
    "elif": "ELIF",
    "while": "WHILE",
    "opt": "OPT",
    "is": "IS",
    "none": "NONE",
    "true": "TRUE",
    "false": "FALSE",
    "let": "LET",
    "import": "IMPORT",
    "match": "MATCH",
    "return": "RETURN",
    "and": "AND",
    "or": "OR",
    "not": "NOT",
    "some": "SOME",
    "start": "START",
    "test": "TEST",
    "const": "CONST",
}

# Double-character operators that must be checked before single ones.
DOUBLE_OPS = {
    "==", "!=", "<=", ">=", "->", "<<", ">>",
}

# Single-character operators.
SINGLE_OPS = set("+-*/%=<>!&|^~.,;:(){}[]←«»↺↻…")


class LexerError(Exception):
    """Raised when the lexer encounters invalid input."""

    def __init__(self, message, line, col):
        self.line = line
        self.col = col
        super().__init__(f"Line {line}, col {col}: {message}")


def _read_string(src, pos, start_line, start_col):
    """Read a double-quoted string literal starting after the opening quote.

    Returns (Token, next_pos).
    """
    text_chars = []
    line = start_line
    col = start_col + 1  # past the opening "
    end_pos = pos

    while end_pos < len(src):
        ch = src[end_pos]
        if ch == "\n":
            line += 1
            col = 0
        elif ch == "\\" and end_pos + 1 < len(src):
            esc = src[end_pos + 1]
            end_pos += 2
            col += 2
            if esc == "n":
                text_chars.append("\n")
            elif esc == "t":
                text_chars.append("\t")
            elif esc == "\\":
                text_chars.append("\\")
            elif esc == '"':
                text_chars.append('"')
            elif esc == "u" and src[end_pos:end_pos + 1] == "{":
                # \u{NNNN} Unicode code point
                hex_end = src.index("}", end_pos + 1)
                hex_str = src[end_pos + 1:hex_end]
                text_chars.append(chr(int(hex_str, 16)))
                end_pos = hex_end + 1
                col += hex_end - end_pos + 2
            else:
                raise LexerError(f"unknown escape '\\{esc}'", line, col)
        elif ch == '"':
            # Closing quote found
            text = "".join(text_chars)
            return Token("STR", text, start_line, start_col), end_pos + 1
        else:
            text_chars.append(ch)
            end_pos += 1
            col += 1

    raise LexerError("unterminated string literal", start_line, start_col)


def _read_int(src, pos, line, col):
    """Read an integer literal with optional type suffix.

    Supports decimal (default), binary (0b prefix), and hexadecimal (0x prefix).
    Type suffixes: u8, i16, u32, i64, u64, etc.

    Returns (Token, next_pos).
    """
    start = pos
    value_str = ""

    # Detect base from prefix.
    if pos + 1 < len(src) and src[pos] == "0" and src[pos + 1] in ("b", "B"):
        base = 2
        value_str += src[pos:pos + 2]
        pos += 2
    elif pos + 1 < len(src) and src[pos] == "0" and src[pos + 1] in ("x", "X"):
        base = 16
        value_str += src[pos:pos + 2]
        pos += 2
    else:
        base = 10

    # Read digits.
    while pos < len(src) and (src[pos].isdigit() or (base == 16 and src[pos] in "abcdefABCDEF")):
        value_str += src[pos]
        pos += 1

    # Try to read type suffix.
    width = ""
    width_start = pos
    while pos < len(src) and (src[pos].isalpha() or src[pos] == "_"):
        width += src[pos]
        pos += 1

    try:
        if base == 2:
            value = int(value_str[2:], 2)
        elif base == 16:
            value = int(value_str[2:], 16)
        else:
            value = int(value_str, 10)
    except ValueError:
        raise LexerError(f"invalid integer literal: {value_str}", line, col)

    if not width:
        width = "int"

    return Token("INT", value, line, col), pos


def tokenize(src: str):
    """Tokenize source code string into a list of tokens.

    Args:
        src: UTF-8 source code string.

    Returns:
        List of Token objects.

    Raises:
        LexerError: on lexical analysis errors.
    """
    tokens = []
    pos = 0
    length = len(src)
    line = 1
    col = 0

    while pos < length:
        ch = src[pos]

        # Whitespace.
        if ch in " \t\r":
            pos += 1
            col += 1
            continue
        if ch == "\n":
            line += 1
            col = 0
            pos += 1
            tokens.append(Token("NEWLINE", "", line, col))
            continue

        # Line comment.
        if ch == "/" and pos + 1 < length and src[pos + 1] == "/":
            end = src.find("\n", pos)
            if end == -1:
                pos = length
            else:
                pos = end + 1
            continue

        # Block comment — count newlines to keep line counter accurate.
        if ch == "/" and pos + 1 < length and src[pos + 1] == "*":
            end = src.find("*/", pos + 2)
            if end == -1:
                raise LexerError("unterminated block comment", line, col)
            # Count newlines inside the block comment.
            comment_text = src[pos:end + 2]
            line += comment_text.count("\n")
            col = len(comment_text) - comment_text.rfind("\n") - 1
            pos = end + 2
            continue

        # @ attribute.
        if ch == "@":
            pos += 1
            col += 1
            name_start = pos
            while pos < length and (src[pos].isalpha() or src[pos] in "_'"):
                pos += 1
            kw = src[name_start:pos]
            token_type = KEYWORDS.get(kw, "IDENT")
            tokens.append(Token(token_type, kw, line, col))
            continue

        # String literal.
        if ch == '"':
            token, pos = _read_string(src, pos + 1, line, col)
            tokens.append(token)
            continue

        # Integer literal.
        if ch.isdigit():
            token, pos = _read_int(src, pos, line, col)
            tokens.append(token)
            continue

        # Double-character operators (check before single-char ones).
        two = src[pos:pos + 2]
        if two in DOUBLE_OPS:
            tokens.append(Token("OP", two, line, col))
            pos += 2
            col += 2
            continue

        # Single-character operators and punctuation.
        if ch in SINGLE_OPS:
            # = is syntactic (variable definition), not an operator.
            if ch == "=" or ch in ",.;:(){}[]…":
                tokens.append(Token("PUNCT", ch, line, col))
            elif ch in "+-*/%<>!&|^~←«»↺↻":
                tokens.append(Token("OP", ch, line, col))
            pos += 1
            col += 1
            continue

        # Identifier or keyword.
        if ch.isalpha() or ch == "_" or ord(ch) > 127:
            name_start = pos
            pos += 1  # Always advance past the first character to avoid infinite loop on non-alnum Unicode chars.
            while pos < length and (src[pos].isalnum() or src[pos] in "_'→"):
                pos += 1
            name = src[name_start:pos]
            token_type = KEYWORDS.get(name, "IDENT")
            tokens.append(Token(token_type, name, line, col))
            col = pos - name_start
            continue

        raise LexerError(f"unexpected character: {ch!r}", line, col)

    # Send a sentinel at end to mark conclusion.
    tokens.append(Token("EOF", None, line, col))
    return tokens


def strip_newlines(tokens):
    """Remove NEWLINE tokens for use in parsing (newlines are structural).

    The parser itself handles newlines as statement terminators; this helper
    is used after initial tokenization when a simpler token stream is needed.
    """
    return [t for t in tokens if t.type != "NEWLINE"]
