"""Lexical analyzer for the NGPL language.

Scans source text (UTF-8) and produces a stream of typed tokens.
Handles identifiers, keywords, integer/string literals, operators,
and punctuation. Skips comments and whitespace.

After tokenization, `process_indentation` inserts INDENT/DEDENT tokens
based on indentation changes, enabling layout-driven scoping.
"""

import math
from interp.errors import coded
import re


class Token:
    """A single lexical token."""

    __slots__ = ("col", "end_col", "line", "type", "value", "width")

    def __init__(self, type_, value, line, col, end_col: int | None = None,
                 width: str | None = None):
        self.type = type_
        self.value = value
        self.line = line
        self.col = col
        self.end_col = end_col if end_col is not None else col + 1
        # The type a numeric literal named in its suffix, or None.
        self.width = width

    def __repr__(self):
        return f"Token({self.type}, {self.value!r}, @{self.line}:{self.col})"


# The full language's transpose operator.  Named here because it is
# wanted in two places -- the identifier scanner has to stop at it, and
# the refusal has to name it -- and because a modifier letter is not
# something to leave sitting bare in a comparison.
TRANSPOSE = "\N{MODIFIER LETTER CAPITAL T}"


# Keywords: maps keyword string to token type.
KEYWORDS = {
    "fn": "FN",
    "mut": "MUT",
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
    "break": "BREAK",
    "continue": "CONTINUE",
    "start": "START",
    "test": "TEST",
    "foreach": "FOREACH",
    "expect": "EXPECT",
    "wrap": "WRAP",
    "enum": "ENUM",
    "flag": "FLAG",
    "replaceable": "REPLACEABLE",
    "export": "EXPORT",
    "catch": "CATCH",
    "comptime": "COMPTIME",
    "type": "TYPE",
    "module": "MODULE",
    "unit": "UNIT",
    "impure": "IMPURE",
    "enumerate": "ENUMERATE",
    "struct": "STRUCT",
    "impl": "IMPL",
    "macro": "MACRO",
}

# Keywords recognized only after the @ prefix.  The @ is part of the
# token — no whitespace may separate it from the name.
AT_KEYWORDS: dict[str, str] = {
    "typeof": "TYPEOF",
    "resultof": "RESULTOF",
    "sizeof": "SIZEOF",
    "unitof": "UNITOF",
    "dropunit": "DROPUNIT",
    # @old(e) in a postcondition: what e was when the call began.
    "old": "OLD",
    # @ignorable: a function whose answer a caller may drop in silence
    "ignorable": "IGNORABLE",
    "min": "MIN",
    "max": "MAX",
    "repr": "REPR",
    "likely": "LIKELY",
    "unlikely": "UNLIKELY",
    "hot": "HOT",
    "cold": "COLD",
    "listable": "LISTABLE",
    "noreturn": "NORETURN",
    "pre": "PRE",
    "post": "POST",
    # @invariant(e) on a struct: what is always true of one.
    "invariant": "INVARIANT",
    # @build heads the build recipe the interpreter reads for search
    # paths and flags; the bare word stays available as a name.
    "build": "BUILD",
    # @import("./x.ngpl") names a file this one is written against.
    # The text is spliced in before this file's own, by the reader,
    # long before the lexer sees any of it; the line survives so that
    # what a file depends on is written in the file, and so that no
    # line number moves.  Here it is only a word to be recognised.
    "import": "AT_IMPORT",
    # @macro_rules heads a macro written as a list of rewrite rules.
    # An annotation rather than a keyword of its own, so the word stays
    # available to a program that wants it as a name.
    "macro_rules": "MACRO_RULES",
}

# Double-character operators that must be checked before single ones.
DOUBLE_OPS = {
    "==", "!=", "<=", ">=", "->", "<-", "<<", ">>", "??",
}

# Multi-character ASCII operators normalized to their Unicode equivalents.
_NORMALIZE_OPS = {
    "<-": "\N{LEFTWARDS ARROW}",
}


# Single-character operators.
# The last six are the tolerant comparisons, paired with the exact ones.
SINGLE_OPS = set("+-%=<>!&|^~.,;:?(){}[]←→«»↺↻…∧∨⊕⊼⊽¬λ⊨⊭⍴⧺⌿⍀¤√∛∜↑⁻×÷⍳∊≠#⸨⸩∪∩∖⊂⊆⊃⊇"
                 # a ⊑ b and a ⊒ b -- a runs along the front of b, or
                 # along its back.
                 "⊑⊒"
                 # f ∀ v, f ∃ v and f ∄ v -- whether f holds of them all,
                 # of any, or of none.
                 "∀∃∄"
                 # Written code: ⟦…⟧ around what a macro is invoked on,
                 # ⟪…⟫ around a piece of program held rather than run,
                 # $ putting a value back into one, and ※ in front of a
                 # name for what the name refers to.
                 "⟦⟧⟪⟫$※"
                 # f¨v -- f applied to each of them, as APL writes it.
                 "\N{DIAERESIS}"
                 "≅≇⪅⪆⪉⪊"
                 # The saturating arithmetic operators.
                 "\N{SQUARED PLUS}\N{SQUARED MINUS}\N{SQUARED TIMES}"
                 # The larger and the smaller of two numbers.
                 "\N{LEFT CEILING}\N{LEFT FLOOR}")

# Binary operators that signal line continuation when trailing.
_CONTINUATION_OPS = frozenset({
    "+", "-", "\N{MULTIPLICATION SIGN}", "\N{DIVISION SIGN}", "%",
    "\N{SQUARED PLUS}", "\N{SQUARED MINUS}", "\N{SQUARED TIMES}",
    "\N{LEFT CEILING}", "\N{LEFT FLOOR}",
    "|", "&", "^",
    "<<", ">>", "«", "»", "↺", "↻",
    "\N{NOT EQUAL TO}", "<", ">", "<=", ">=",
    "≅",
    "≇",
    "⪅",
    "⪆",
    "⪉",
    "⪊",
    "??", "←",
    "∧", "∨", "⊕", "⊼", "⊽",
    "⍴",
    "⍳",
    "\N{SMALL ELEMENT OF}",
    "\N{UNION}", "\N{INTERSECTION}", "\N{SET MINUS}",
    "\N{SUBSET OF}", "\N{SUBSET OF OR EQUAL TO}",
    "⧺",
    "\N{APL FUNCTIONAL SYMBOL SLASH BAR}",
    "\N{APL FUNCTIONAL SYMBOL BACKSLASH BAR}",
})


class LexerError(Exception):
    """Raised when the lexer encounters invalid input.

    `incomplete` says whether more input could still finish what was
    started — an unterminated string or block comment — as opposed to
    input that no continuation can repair.  At the prompt the first
    kind means keep reading and the second means report now.
    """

    def __init__(self, message, line, col, incomplete: bool = False):
        self.line = line
        self.col = col
        self.incomplete = incomplete
        super().__init__(f"Line {line}, col {col}: {message}")


def _read_string(src, pos, start_line, start_col, line_start):
    """Read a double-quoted string literal starting after the opening quote.

    Three quotes open one that may run over several lines.  Every line
    after the first begins with a quote, which may be indented as the
    code around it is, and neither that quote nor the whitespace before
    it nor the line break itself is part of what the string holds: the
    pieces are joined as they were written, and a line break inside the
    text is written \n as it is in any other string.  The string ends at
    the next three quotes, so a single quote needs no escape inside one.

    Returns (Token, next_pos).
    """
    text_chars = []
    line = start_line
    cur_line_start = line_start
    multi = src[pos:pos + 2] == '""'
    if multi:
        pos += 2
    end_pos = pos

    while end_pos < len(src):
        ch = src[end_pos]
        if multi and src[end_pos:end_pos + 3] == '"""':
            text = "".join(text_chars)
            end_col = end_pos + 3 - cur_line_start
            return Token("STR", text, start_line, start_col, end_col), end_pos + 3
        if ch == "\n":
            if multi:
                end_pos += 1
                line += 1
                cur_line_start = end_pos
                while end_pos < len(src) and src[end_pos] in " \t":
                    end_pos += 1
                if src[end_pos:end_pos + 3] == '"""':
                    text = "".join(text_chars)
                    end_col = end_pos + 3 - cur_line_start
                    return Token("STR", text, start_line, start_col, end_col), end_pos + 3
                if src[end_pos:end_pos + 1] != '"':
                    raise LexerError(
                        "a line continuing a multi-line string begins with a "
                        "quote, and what stands before that quote is not part "
                        "of the string",
                        line, end_pos - cur_line_start)
                end_pos += 1
                continue
            else:
                # A simple string ends before the line does; a newline
                # inside one is an unterminated string, not a longer one.
                # (This used to advance nothing and hang the scanner.)
                raise LexerError(
                    "string literal is not closed before the end of the line",
                    start_line, start_col)
        elif ch == "\\" and end_pos + 1 < len(src):
            esc = src[end_pos + 1]
            end_pos += 2
            if esc == "n":
                text_chars.append("\n")
            elif esc == "t":
                text_chars.append("\t")
            elif esc == "\\":
                text_chars.append("\\")
            elif esc == '"':
                text_chars.append('"')
            elif esc == "u" and src[end_pos:end_pos + 1] == "{":
                hex_end = src.index("}", end_pos + 1)
                hex_str = src[end_pos + 1:hex_end]
                text_chars.append(chr(int(hex_str, 16)))
                end_pos = hex_end + 1
            else:
                raise LexerError(f"unknown escape '\\{esc}'", line, end_pos - cur_line_start)
        elif ch == '"' and not multi:
            text = "".join(text_chars)
            end_col = end_pos + 1 - cur_line_start
            return Token("STR", text, start_line, start_col, end_col), end_pos + 1
        else:
            text_chars.append(ch)
            end_pos += 1

    raise LexerError("unterminated string literal", start_line, start_col,
                     incomplete=True)


def _check_literal_width(width: str, is_float: bool, text: str, line, col):
    """Refuse a suffix that does not name a type the literal can have.

    A suffix says what the number is, so one that names nothing is a
    mistake rather than a decoration; and a whole number cannot be
    spelled with a float type, nor a fractional one with an integer
    type.
    """
    from interp.value import (BUILTIN_TYPES, FLOAT_TYPES, FAST_TYPES,
                              _parse_int_width)
    known = (width in BUILTIN_TYPES or width in FAST_TYPES
             or _parse_int_width(width) is not None)
    if not known:
        raise LexerError(
            f"'{width}' is not a type, so it cannot be the suffix of "
            f"{text}", line, col)
    if is_float and width not in FLOAT_TYPES:
        raise LexerError(
            f"{text} is a floating-point literal, so its suffix cannot be "
            f"'{width}'", line, col)
    if not is_float and width in FLOAT_TYPES:
        return
    return


def _literal_digits_are_zero(text: str, base: int) -> bool:
    """Whether the digits of a numeric literal spell zero.

    Only the significand is read: an exponent scales a number and
    cannot make a nonzero one zero.  This is what says whether `0.0`
    was written or a number that reached zero on the way in, which the
    parsed value can no longer tell -- float("1e-400") is 0.0 as
    surely as float("0.0") is.
    """
    digits = text[2:] if base == 16 else text
    for mark in "eEpP":
        digits = digits.split(mark)[0]
    return set(digits.replace(".", "")) <= {"0"}


def _check_float_literal_range(value: float, width: str, text: str, base: int,
                               line, col):
    """Refuse a literal whose value its type cannot hold.

    A number too large for its format becomes an infinity and one too
    small becomes a zero.  Either way it is a different number from the
    one that was written, and a literal is a mistake in the source, so
    the source is where it is reported.
    """
    from interp.value import (float_overflow_message, float_overflows,
                              float_underflow_message, float_underflows)
    if math.isinf(value) or float_overflows(value, width):
        # The value is an infinity because the text overflowed, so the
        # text is what the complaint has to name.
        raise coded(2293, LexerError(
            float_overflow_message(text, width), line, col))
    if _literal_digits_are_zero(text, base):
        return
    if value == 0.0 or float_underflows(value, width):
        raise LexerError(float_underflow_message(text, width), line, col)


def _read_char(src, pos, line, col, line_start):
    """Read a character literal starting after the opening quote.

    One character between apostrophes, which is what the value holds.
    A string is written with double quotes, so the two say which they
    are before anything is read: `\'a\'` is a character and `"a"` a
    string of one.

    Returns (Token, next_pos).
    """
    from interp.value import check_code_point
    chars: list[str] = []
    end_pos = pos

    while end_pos < len(src) and src[end_pos] not in ("'", "\n"):
        ch = src[end_pos]
        if ch == "\\" and end_pos + 1 < len(src):
            esc = src[end_pos + 1]
            end_pos += 2
            if esc == "n":
                chars.append("\n")
            elif esc == "t":
                chars.append("\t")
            elif esc == "r":
                chars.append("\r")
            elif esc == "\\":
                chars.append("\\")
            elif esc in ("'", '"'):
                chars.append(esc)
            elif esc == "u" and src[end_pos:end_pos + 1] == "{":
                closing = src.find("}", end_pos + 1)
                if closing < 0:
                    raise LexerError(
                        "\\u{ needs a closing brace", line, col)
                digits = src[end_pos + 1:closing]
                try:
                    code = int(digits, 16)
                except ValueError:
                    raise LexerError(
                        f"'{digits}' is not a hexadecimal number",
                        line, col) from None
                try:
                    check_code_point(code, "character literal")
                except TypeError as e:
                    raise LexerError(str(e), line, col) from None
                chars.append(chr(code))
                end_pos = closing + 1
            else:
                raise LexerError(f"unknown escape '\\{esc}'", line, col)
            continue
        chars.append(ch)
        end_pos += 1

    if end_pos >= len(src) or src[end_pos] != "'":
        raise LexerError(
            "a character literal ends on the line it starts, with '",
            line, col)
    if len(chars) != 1:
        written = "".join(chars)
        if not chars:
            raise LexerError(
                "a character literal holds one character, and this one "
                "holds none; a string of no characters is written \"\"",
                line, col)
        raise LexerError(
            f"a character literal holds one character, and '{written}' "
            f"holds {len(chars)}; a string is written with double quotes, "
            f"as \"{written}\"", line, col)
    end_col = end_pos + 1 - line_start
    return (Token("CHAR", ord(chars[0]), line, col, end_col), end_pos + 1)


def _read_number(src, pos, line, col):
    """Read a numeric literal (integer or float) with optional type suffix.

    Integers: decimal, binary (0b), hexadecimal (0x).
    Floats: decimal with '.' or exponent (e/E), hex with '.' or exponent (p/P).
    Type suffixes: u8, i16, f32, f64, bfloat16, etc.

    Returns (Token, next_pos).
    """
    start_pos = pos
    value_str = ""
    is_float = False

    if pos + 1 < len(src) and src[pos] == "0" and src[pos + 1] in "bBxX":
        base = 2 if src[pos + 1] in "bB" else 16
        pos += 2
    else:
        base = 10

    while pos < len(src) and (src[pos].isdigit() or (base == 16 and src[pos] in "abcdefABCDEF")):
        value_str += src[pos]
        pos += 1

    if base != 2 and pos < len(src) and src[pos] == ".":
        next_pos = pos + 1
        if next_pos < len(src) and (src[next_pos].isdigit() or (base == 16 and src[next_pos] in "abcdefABCDEF")):
            is_float = True
            value_str += "."
            pos = next_pos
            while pos < len(src) and (src[pos].isdigit() or (base == 16 and src[pos] in "abcdefABCDEF")):
                value_str += src[pos]
                pos += 1

    if pos < len(src) and base != 2 and src[pos] in ("eE" if base == 10 else "pP"):
          is_float = True
          value_str += src[pos]
          pos += 1
          if pos < len(src) and src[pos] in "+-":
              value_str += src[pos]
              pos += 1
          while pos < len(src) and src[pos].isdigit():
              value_str += src[pos]
              pos += 1

    width = ""
    while pos < len(src) and (src[pos].isalnum() or src[pos] == "_"):
        width += src[pos]
        pos += 1

    end_col = col + (pos - start_pos)

    if width:
        _check_literal_width(width, is_float, value_str, line, col)

    from interp.value import FLOAT_TYPES as _FLOATS
    if is_float or width in _FLOATS:
        try:
            if base == 16:
                value = float.fromhex(value_str)
            else:
                value = float(value_str)
        except ValueError:
            raise LexerError(f"invalid float literal: {value_str}", line, col)
        except OverflowError:
            # float.fromhex says so rather than answering with one.
            from interp.value import float_overflow_message
            raise LexerError(
                float_overflow_message(value_str, width or "float"),
                line, col) from None
        if not width:
            width = "float"
        _check_float_literal_range(value, width, value_str, base, line, col)
        return Token("FLOAT", (value, width), line, col, end_col), pos

    try:
        value = int(value_str, base)
    except ValueError:
        raise LexerError(f"invalid integer literal: {value_str}", line, col)

    if not width:
        width = "int"

    return Token("INT", value, line, col, end_col, width=width), pos


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
    line_start = 0
    indent_char: str | None = None

    while pos < length:
        ch = src[pos]
        col = pos - line_start

        # Whitespace (not newline).
        if ch in " \t\r":
            pos += 1
            continue

        # Newline — also measures the indentation of the following line.
        if ch == "\n":
            line += 1
            pos += 1
            line_start = pos
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
                raise LexerError("unterminated block comment", line, col,
                                 incomplete=True)
            comment_text = src[pos:end + 2]
            nl_count = comment_text.count("\n")
            if nl_count > 0:
                line += nl_count
                line_start = pos + comment_text.rfind("\n") + 1
            pos = end + 2
            continue

        # @ attribute.
        if ch == "@":
            at_col = col
            pos += 1
            name_start = pos
            while pos < length and (src[pos].isalpha() or src[pos] in "_'"):
                pos += 1
            kw = src[name_start:pos]
            token_type = AT_KEYWORDS.get(kw) or KEYWORDS.get(kw)
            if token_type is None:
                # An unknown annotation must not shed its @ and walk on
                # as a name; it is refused where it stands, by name.
                raise LexerError(
                    f"'@{kw}' is not an annotation the bootstrap "
                    f"provides", line, at_col)
            tokens.append(Token(token_type, kw, line, at_col, pos - line_start))
            continue

        # The full language's optional glyphs are refused by name
        # rather than walking on as identifier characters.
        if ch in "\N{APL FUNCTIONAL SYMBOL QUAD QUESTION}\N{WARNING SIGN}":
            what = ("asks an optional for its value"
                    if ch == "\N{APL FUNCTIONAL SYMBOL QUAD QUESTION}"
                    else "takes an optional's value or fails")
            raise LexerError(
                f"'{ch}' {what}, which the bootstrap does not provide "
                f"yet; ?? and match serve meanwhile", line, col)

        if ch == TRANSPOSE:
            raise LexerError(
                f"'{ch}' transposes a matrix, which the bootstrap does "
                f"not provide yet; write the two loops meanwhile",
                line, col)

        # String literal.
        if ch == '"':
            str_start = pos
            token, pos = _read_string(src, pos + 1, line, col, line_start)
            spanned = src[str_start:pos]
            nl_count = spanned.count("\n")
            if nl_count > 0:
                line += nl_count
                line_start = str_start + spanned.rfind("\n") + 1
            tokens.append(token)
            continue

        # Character literal.  A ' that continues an identifier -- the
        # prime of a generic type name -- is taken by the identifier
        # scanner, so one reaching here opens a literal.
        if ch == "'":
            token, pos = _read_char(src, pos + 1, line, col, line_start)
            tokens.append(token)
            continue

        # Numeric literal (integer or float).
        if ch.isdigit():
            token, pos = _read_number(src, pos, line, col)
            tokens.append(token)
            continue

        # Double-character operators (check before single-char ones).
        two = src[pos:pos + 2]
        if two in DOUBLE_OPS:
            tokens.append(Token("OP", _NORMALIZE_OPS.get(two, two), line, col, col + 2))
            pos += 2
            continue

        # Single-character operators and punctuation.
        if ch in SINGLE_OPS:
            if ch == "λ":
                tokens.append(Token("LAMBDA", ch, line, col))
            elif ch == "\N{NOT TRUE}":
                # ⊭(e) is a failed result carrying the reason.
                tokens.append(Token("NOTSOME", ch, line, col))
            elif ch == "\N{TRUE}":
                # ⊨(v) is the present optional; the same token as the
                # `some` keyword it spells more briefly.
                tokens.append(Token("SOME", ch, line, col))
            elif ch == "=" or ch in ",.;:(){}[]…⸨⸩⟦⟧⟪⟫$":
                tokens.append(Token("PUNCT", ch, line, col))
            elif ch == "\N{RIGHTWARDS ARROW}":
                tokens.append(Token("OP", "->", line, col))
            elif ch in ("+-%<>!&|^~?←«»↺↻∧∨⊕⊼⊽¬⍴⧺⌿⍀¤√∛∜↑⁻⍳∊≠#∪∩∖⊂⊆⊃⊇⊑⊒※∀∃∄\N{DIAERESIS}"
                        "\N{MULTIPLICATION SIGN}\N{DIVISION SIGN}"
                        "≅≇⪅⪆⪉⪊"
                        "\N{SQUARED PLUS}\N{SQUARED MINUS}"
                        "\N{SQUARED TIMES}"
                        "\N{LEFT CEILING}\N{LEFT FLOOR}"):
                tokens.append(Token("OP", ch, line, col))
            else:
                # Reaching here means the character was added to
                # SINGLE_OPS but to none of the branches above, which
                # would otherwise drop it without a token.
                raise LexerError(
                    f"operator {ch!r} has no token kind", line, col)
            pos += 1
            continue

        # Identifier or keyword.
        if ch.isalpha() or ch == "_" or ord(ch) > 127:
            name_start = pos
            pos += 1
            while pos < length and (src[pos].isalnum() or src[pos] in "_'"):
                # 'ᵀ' is a modifier letter, so isalnum() answers yes for
                # it; left alone the name would swallow the transpose
                # that follows it and the refusal below would never be
                # reached.  A name ends where the operator begins.
                if src[pos] == TRANSPOSE:
                    break
                pos += 1
            name = src[name_start:pos]
            token_type = KEYWORDS.get(name, "IDENT")
            tokens.append(Token(token_type, name, line, col, pos - line_start))
            continue

        if ch == "/":
            # Reached only when the comment openings above did not
            # match, so this is a lone slash where division was meant.
            raise LexerError(
                "'/' is not an operator; division is written "
                "'\N{DIVISION SIGN}'.  A slash begins a comment, as "
                "'//' or '/*'", line, col)

        raise LexerError(f"unexpected character: {ch!r}", line, col)

    # Send a sentinel at end to mark conclusion.
    tokens.append(Token("EOF", None, line, pos - line_start))
    return tokens


def process_indentation(tokens: list[Token]) -> list[Token]:
    """Insert INDENT and DEDENT tokens based on indentation changes.

    Indentation processing is suppressed inside (), [] and {} nesting.
    A line ending with a binary operator is treated as a continuation;
    no INDENT/DEDENT is emitted for the following line.

    Braces are among them because a struct literal is written with
    them, and one worth spreading over several lines -- a machine
    description, a header -- must not have its own lines read as a
    block.  The cost is that layout cannot be nested inside braces: a
    block written in braces holds statements separated by ';', and a
    block inside it is written in braces too.  The compiler makes the
    same trade, and the two have to agree about what a program means.
    """
    result: list[Token] = []
    indent_stack = [0]
    nesting = 0
    i = 0

    while i < len(tokens):
        tok = tokens[i]

        if tok.type == "PUNCT" and tok.value in ("(", "[", "{"):
            nesting += 1
            result.append(tok)
            i += 1
            continue

        if tok.type == "PUNCT" and tok.value in (")", "]", "}"):
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
        # An operator right after ※ is a name rather than an operation,
        # so a line ending in one is finished rather than continued.
        before = None
        for k in range(len(result) - 3, -1, -1):
            if result[k].type not in ("NEWLINE", "INDENT", "DEDENT"):
                before = result[k]
                break
        names_an_operator = (before is not None and before.type == "OP"
                             and before.value == "※")
        if prev and not names_an_operator and (
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
