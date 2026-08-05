"""Lexical analyzer for the newlang language.

Scans source text (UTF-8) and produces a stream of typed tokens.
Handles identifiers, keywords, integer/string literals, operators,
and punctuation. Skips comments and whitespace.

After tokenization, `process_indentation` inserts INDENT/DEDENT tokens
based on indentation changes, enabling layout-driven scoping.
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
    "∅": "NONE",
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
    "foreach": "FOREACH",
    "expect": "EXPECT",
    "wrap": "WRAP",
    "enum": "ENUM",
    "flag": "FLAG",
    "replaceable": "REPLACEABLE",
    "catch": "CATCH",
}

# Double-character operators that must be checked before single ones.
DOUBLE_OPS = {
    "==", "!=", "<=", ">=", "->", "<<", ">>", "??",
}

# Single-character operators.
SINGLE_OPS = set("+-*/%=<>!&|^~.,;:?(){}[]←«»↺↻…∧∨⊕⊼⊽¬λ⍴⧺")

# Binary operators that signal line continuation when trailing.
_CONTINUATION_OPS = frozenset({
    "+", "-", "*", "/", "%",
    "|", "&", "^",
    "<<", ">>", "«", "»", "↺", "↻",
    "==", "!=", "<", ">", "<=", ">=",
    "??", "←",
    "∧", "∨", "⊕", "⊼", "⊽",
    "⍴",
    "⧺",
})


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

    NEWLINE tokens carry the indentation level of the following line
    as their value (int).  Indentation must use either all spaces or
    all tabs throughout the file; mixing is a lexer error.

    Args:
        src: UTF-8 source code string.

    Returns:
        List of Token objects.

    Raises:
        LexerError: on lexical analysis errors.
    """
    tokens: list[Token] = []
    pos = 0
    length = len(src)
    line = 1
    col = 0
    indent_char: str | None = None

    while pos < length:
        ch = src[pos]

        # Whitespace (not newline).
        if ch in " \t\r":
            pos += 1
            col += 1
            continue

        # Newline — also measures the indentation of the following line.
        if ch == "\n":
            line += 1
            pos += 1
            indent = 0
            while pos < length and src[pos] in " \t":
                ic = src[pos]
                if indent_char is None:
                    indent_char = ic
                elif ic != indent_char:
                    exp = "tabs" if indent_char == "\t" else "spaces"
                    got = "tab" if ic == "\t" else "space"
                    raise LexerError(
                        f"mixed indentation: expected {exp}, got {got}",
                        line, indent)
                indent += 1
                pos += 1
            col = indent
            tokens.append(Token("NEWLINE", indent, line, 0))
            continue

        # Line comment — stop before the newline so the \n handler runs.
        if ch == "/" and pos + 1 < length and src[pos + 1] == "/":
            end = src.find("\n", pos)
            if end == -1:
                pos = length
            else:
                pos = end
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
            if ch == "λ":
                tokens.append(Token("LAMBDA", ch, line, col))
            elif ch == "=" or ch in ",.;:(){}[]…":
                tokens.append(Token("PUNCT", ch, line, col))
            elif ch in "+-*/%<>!&|^~?←«»↺↻∧∨⊕⊼⊽¬⍴⧺":
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


def process_indentation(tokens: list[Token]) -> list[Token]:
    """Insert INDENT and DEDENT tokens based on indentation changes.

    Indentation processing is suppressed inside () and [] nesting.
    A line ending with a binary operator is treated as a continuation;
    no INDENT/DEDENT is emitted for the following line.
    """
    result: list[Token] = []
    indent_stack = [0]
    nesting = 0
    i = 0

    while i < len(tokens):
        tok = tokens[i]

        if tok.type == "PUNCT" and tok.value in ("(", "["):
            nesting += 1
            result.append(tok)
            i += 1
            continue

        if tok.type == "PUNCT" and tok.value in (")", "]"):
            if nesting > 0:
                nesting -= 1
            result.append(tok)
            i += 1
            continue

        if tok.type != "NEWLINE":
            result.append(tok)
            i += 1
            continue

        # --- NEWLINE token ---
        result.append(tok)

        if nesting > 0:
            i += 1
            continue

        # Trailing binary operator ⇒ line continuation.
        prev = None
        for k in range(len(result) - 2, -1, -1):
            if result[k].type not in ("NEWLINE", "INDENT", "DEDENT"):
                prev = result[k]
                break
        if prev and (
            (prev.type == "OP" and prev.value in _CONTINUATION_OPS)
            or prev.type in ("AND", "OR")
            or (prev.type == "PUNCT" and prev.value == "=")
        ):
            i += 1
            continue

        # Collect consecutive NEWLINEs (blank lines).
        j = i + 1
        while j < len(tokens) and tokens[j].type == "NEWLINE":
            result.append(tokens[j])
            j += 1

        # Effective indent = indent of the last NEWLINE before content.
        if j > i + 1:
            indent = tokens[j - 1].value
        else:
            indent = tok.value
        if not isinstance(indent, int):
            indent = 0

        # End of file: close all open indent levels.
        if j >= len(tokens) or tokens[j].type == "EOF":
            while len(indent_stack) > 1:
                indent_stack.pop()
                result.append(Token("DEDENT", "", tok.line, 0))
            i = j
            continue

        # Emit INDENT or DEDENT tokens.
        if indent > indent_stack[-1]:
            indent_stack.append(indent)
            result.append(Token("INDENT", "", tok.line, 0))
        else:
            while indent < indent_stack[-1]:
                indent_stack.pop()
                result.append(Token("DEDENT", "", tok.line, 0))
            if indent > indent_stack[-1]:
                indent_stack.append(indent)
                result.append(Token("INDENT", "", tok.line, 0))

        i = j
        continue

    # Close remaining indent levels at end of input.
    while len(indent_stack) > 1:
        indent_stack.pop()
        result.append(Token("DEDENT", "", 0, 0))

    return result


def strip_newlines(tokens):
    """Remove NEWLINE/INDENT/DEDENT tokens when a flat stream is needed."""
    return [t for t in tokens if t.type not in ("NEWLINE", "INDENT", "DEDENT")]
