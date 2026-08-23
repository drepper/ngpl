"""Runtime value types for the NGPL language.

Each runtime value is wrapped in one of these classes. The evaluator
operates on these values rather than raw Python objects to support
type checking and proper error messages.
"""

import functools as _functools
import math
import re
from interp.errors import coded, Diagnostic


class _WidthMiss:
    """Absence in the width table, told apart from a stored None."""


_WIDTH_MISS = _WidthMiss()


# The discard target.  Assigning to it evaluates the right-hand side and
# throws the result away; it names no storage, so it never needs to be
# declared and can never be read back.
DISCARD_NAME = "_"

BUILTIN_TYPES: set[str] = {
    "i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64",
    "usize", "int", "bool", "∅", "byte", "str", "char",
    "i8fast", "u8fast", "i16fast", "u16fast",
    "i32fast", "u32fast", "i64fast", "u64fast",
    "f16", "f32", "f64", "bfloat16", "float",
    # Everything that can be called answers to one name, so a generic
    # that meets a named function in one place and a lambda in another
    # is not told they are two different types.
    "fn",
    # A piece of the program, which is what a macro is handed and what
    # it answers.
    "syntax",
    # One run of bytes waiting to be written, as std.iov settles it.
    "std.iovec",
}

# Platform-specific fast type mapping (x86_64: sub-32 → 32, 32/64 → 64).
_FAST_TYPE_UNDERLYING: dict[str, str] = {
    "u8fast": "u32", "i8fast": "i32",
    "u16fast": "u32", "i16fast": "i32",
    "u32fast": "u64", "i32fast": "i64",
    "u64fast": "u64", "i64fast": "i64",
}

FAST_TYPES: frozenset[str] = frozenset(_FAST_TYPE_UNDERLYING)

# The integer types that carry a name of their own rather than stating
# a width.  Every other iN or uN is read from the name itself.
_NAMED_TYPE_BITS: dict[str, int] = {
    "byte": 8,
    "usize": 64,
    "u8fast": 32, "i8fast": 32,
    "u16fast": 32, "i16fast": 32,
    "u32fast": 64, "i32fast": 64,
    "u64fast": 64, "i64fast": 64,
}

# The widest variable the language will hold.  Beyond this a value is
# no longer a machine integer in any useful sense, and arbitrary
# precision is what `int` is for.
#
# A signed type is counted with its sign against this, so the widest
# signed type is one narrower than the widest unsigned one.  What each
# width means is unchanged: iN is N bits holding -2**(N-1)..2**(N-1)-1,
# as i8 and i64 always have.
MAX_INT_BITS = 128


@_functools.lru_cache(maxsize=None)
def _parse_int_width(name: str) -> int | None:
    """The bit count an integer type name states, or None if it states none.

    `i32` and `u7` state theirs; `byte` and `usize` carry names instead
    and are looked up.

    A width names a type only when it leaves at least one bit for the
    value and fits a variable: a signed type spends a bit on the sign,
    so i1 holds nothing, and the sign counts against the width a
    variable may reach, which makes i127 the widest signed type where
    u128 is the widest unsigned one.
    """
    if len(name) < 2 or name[0] not in "iu" or not name[1:].isdigit():
        return None
    bits = int(name[1:])
    unsigned = name[0] == "u"
    value_bits = bits if unsigned else bits - 1
    limit = MAX_INT_BITS if unsigned else MAX_INT_BITS - 1
    if value_bits < 1 or bits > limit:
        return None
    return bits


class _IntWidths:
    """The bit count of every integer type, named or written out.

    Behaves as the mapping the rest of the code already expects, so a
    width stated in a name needs no special case at the places that ask
    for one.
    """

    __slots__ = ("_named",)

    def __init__(self, named: dict[str, int]):
        self._named = named

    def get(self, name, default=None):
        got = self._named.get(name, _WIDTH_MISS)
        if got is not _WIDTH_MISS:
            return got
        bits = _parse_int_width(name) if isinstance(name, str) else None
        return default if bits is None else bits

    def __getitem__(self, name):
        bits = self.get(name)
        if bits is None:
            raise KeyError(name)
        return bits

    def __contains__(self, name):
        # the named widths are most of the questions, and answering
        # from the table costs less than the call that would
        if name in self._named:
            return True
        return self.get(name) is not None

    def __iter__(self):
        return iter(self._named)


_TYPE_BITS = _IntWidths(_NAMED_TYPE_BITS)


# The width of an integer literal that named none.  It is not a type a
# program can write: an untyped value settles on one the moment it is
# bound or combined with something that has one.  See spec/spec.md,
# "Untyped Integer Constants".
UNTYPED = "untyped"


def is_unwidthed(width: str) -> bool:
    """Whether a width fixes no number of bits.

    True for `int`, which is arbitrary precision, and for an untyped
    literal, which has not settled on anything yet.  Both are places
    where a bit count cannot be asked for.
    """
    return width in ("int", UNTYPED)


def unsettled_kind(value: "Value") -> str | None:
    """What a value would have to settle on, where that is not provided.

    Answers "int" or "float" for a value still carrying no width, and
    None for anything the bootstrap can hold.  A binding without a
    stated type would commit such a value to the arbitrary-precision
    type, which the bootstrap does not implement.
    """
    if isinstance(value, IntValue) and is_unwidthed(value.width):
        return "int"
    if isinstance(value, FloatValue) and value.width == "float":
        return "float"
    if isinstance(value, (UnitValue, SomeValue)):
        inner = value.inner if isinstance(value, UnitValue) else value.value
        return unsettled_kind(inner)
    if isinstance(value, ExpectedValue) and value.is_ok():
        # A division answers with what it worked out or with why it
        # could not; the value inside is what the binding would keep.
        return unsettled_kind(value.ok_value)
    if isinstance(value, ObjectValue) and isinstance(value.obj, ArrayValue):
        # An array of numbers that have settled on nothing is an array
        # of the type the bootstrap does not have.  An element type is
        # what the array settled on, and one element saying what it is
        # is enough to settle the rest; where nothing said, the
        # elements are asked one at a time.
        array = value.obj
        if array.element_type is not None:
            return ("int" if is_unwidthed(array.element_type)
                    else "float" if array.element_type == "float"
                    else None)
        for element in array.values():
            kind = unsettled_kind(element)
            if kind is not None:
                return kind
        return None
    if isinstance(value, TupleValue):
        # A tuple settles nothing between its elements: each is its own
        # type, so each number states its own width or states none.
        for element in value.elements:
            kind = unsettled_kind(element)
            if kind is not None:
                return kind
    return None


def check_bootstrap_argument(value: "Value", where: str):
    """Refuse an argument no sized type could hold.

    A parameter that states a type settles the value against it, and a
    binding that states one settles it there.  What is left is a value
    handed to something that states nothing -- a builtin, or an untyped
    parameter -- where nothing says what type it should have.  A number
    that would fit one is left alone: it is the arbitrary precision
    that the bootstrap does not have, not the not-yet-settledness.
    """
    inner = value
    while isinstance(inner, (UnitValue, SomeValue)):
        inner = inner.inner if isinstance(inner, UnitValue) else inner.value
    if not isinstance(inner, IntValue) or not is_unwidthed(inner.width):
        return
    # The widest sized types the language has: an unsigned one spends
    # no bit on the sign, and a signed one spends the top bit.
    if _int_range(f"i{MAX_INT_BITS - 1}")[0] <= inner.value \
            <= _int_range(f"u{MAX_INT_BITS}")[1]:
        return
    raise coded(2617, TypeError(
        f"{where}: {inner.value} needs more bits than any sized type "
        f"has, and nothing here says which type it should have; the "
        f"bootstrap implementation has no arbitrary-precision int for "
        f"it to settle on"))


def suggested_type(value: "Value") -> str:
    """A type a binding of this value could state.

    What settled on nothing is suggested as the sized type it would
    have taken, and everything else is named as what it already is, so
    the answer reads as the program would write it: `i64`, `i64[]`,
    `(i64, str)`, `(i64, str)[]`.

    A dimension is a comma inside one pair of brackets, so an array of
    arrays is `i64[,]` rather than `i64[][]`.
    """
    if isinstance(value, TupleValue):
        return "(" + ", ".join(suggested_type(e) for e in value.elements) + ")"
    dims = 0
    while isinstance(value, ObjectValue) and isinstance(value.obj, ArrayValue):
        dims += 1
        inner = value.obj.values()
        if not inner:
            return "i64" + "[" + "," * dims_comma(dims) + "]"
        value = inner[0]
    if dims:
        return suggested_type(value) + "[" + "," * (dims - 1) + "]"
    if isinstance(value, IntValue) and is_unwidthed(value.width):
        return _FULL_LANGUAGE_TYPES["int"]
    if isinstance(value, FloatValue) and value.width == "float":
        return _FULL_LANGUAGE_TYPES["float"]
    if isinstance(value, (UnitValue, SomeValue)):
        return suggested_type(value.inner if isinstance(value, UnitValue)
                              else value.value)
    return runtime_type_of(value)


def dims_comma(dims: int) -> int:
    """The commas an array type of this many dimensions carries."""
    return max(dims - 1, 0)


def _holds_nothing(value: "Value") -> bool:
    """Whether an array has nothing in it at any depth.

    Rows of rows of nothing are still nothing: what an array holds is
    settled by something in it, and there is nothing in it to do the
    settling.
    """
    inner = value.value if isinstance(value, SomeValue) else value
    if not isinstance(inner, ObjectValue):
        return False
    if isinstance(inner.obj, HashValue):
        held = inner.obj
        return (held.key_type is None and held.value_type is None
                and held.sizeof == 0)
    if isinstance(inner.obj, SetValue):
        return inner.obj.value_type is None and inner.obj.sizeof == 0
    if not isinstance(inner.obj, ArrayValue):
        return False
    arr = inner.obj
    if arr.element_type is not None:
        return False
    return all(_holds_nothing(arr.get(i)) for i in range(arr.sizeof))


def check_binding_settles(value: "Value", name: str):
    """Refuse a binding that nothing could ever say the type of.

    An empty array says nothing about what it would hold, and a binding
    with no type written down says nothing either, so between them
    there is no type -- and a name with no type is a name nothing can
    be checked against afterwards.  Being empty is not the objection: a
    dynamic array is allowed to hold nothing, and one whose type is
    written down holds nothing of that type.
    """
    if not _holds_nothing(value):
        return
    inner = value.value if isinstance(value, SomeValue) else value
    if isinstance(inner, ObjectValue) and isinstance(inner.obj, (HashValue,
                                                                 SetValue)):
        raise coded(2775, TypeError(
            f"'{name}': \N{LEFT DOUBLE PARENTHESIS}\N{RIGHT DOUBLE PARENTHESIS} "
            f"is empty, so it says neither what it holds nor whether it is a "
            f"dictionary or a set, and the binding says nothing either; state a "
            f"type, as 'let {name} : std.dict(str, i64) = "
            f"\N{LEFT DOUBLE PARENTHESIS}\N{RIGHT DOUBLE PARENTHESIS}'"))
    raise coded(2776, TypeError(
        f"'{name}': an empty array says nothing about what it would "
        f"hold, and the binding says nothing either; state a type, as "
        f"'let {name} : i64[] = []'"))


def check_bootstrap_binding(value: "Value", name: str):
    """Refuse a binding that would hold an arbitrary-precision value.

    A type written down is what asks for a representation, and without
    one a number settles on `int` or `float` -- the two types the
    bootstrap does not provide.  The literal itself is not the problem
    and is left alone: it is arbitrary-precision only while it is being
    computed with, and settles on the type it is used at.  Naming it is
    what asks for it to be kept.
    """
    kind = unsettled_kind(value)
    if kind is None:
        return
    raise coded(2278, TypeError(
        f"'{name}': a binding with no type written down settles on "
        f"'{kind}', which is an arbitrary-precision type the bootstrap "
        f"implementation does not provide; state a sized type, as "
        f"'let {name} : {suggested_type(value)} = "
        f"\N{HORIZONTAL ELLIPSIS}'"))


def settle_untyped(value: "Value") -> "Value":
    """Commit an untyped integer to `int`, as a binding does.

    A literal is untyped only while it is being computed with.  Naming
    the result settles it, and what it settles on without a stated type
    is `int` — arbitrary precision, so nothing is lost by the move.
    """
    if isinstance(value, IntValue) and value.width == UNTYPED:
        return IntValue(value.value, "int")
    if isinstance(value, UnitValue):
        inner = settle_untyped(value.inner)
        return value if inner is value.inner else UnitValue(inner, value.unit)
    if isinstance(value, SomeValue):
        inner = settle_untyped(value.value)
        return value if inner is value.value else SomeValue(inner)
    return value


class _IntMasks:
    """The value mask of every integer type, derived from its width."""

    __slots__ = ()

    def get(self, name, default=None):
        bits = _TYPE_BITS.get(name)
        return default if bits is None else (1 << bits) - 1

    def __contains__(self, name):
        return name in _TYPE_BITS


_TYPE_MASK = _IntMasks()


def resolve_width(w1: str, w2: str) -> str:
    """Determine the result type when combining two integer types.

    Three kinds of operand meet here, and they rank:

    - An *untyped* literal is not committed to anything, so it takes
      the type of what it is combined with: the 1 in `p + 1` is a u8
      where p is, as an untyped constant is in Go.  The result is then
      subject to that type's range, and can overflow or wrap where a
      value of that type would.
    - `int` is arbitrary precision, which is wider than any fixed
      width, so it wins against one.  A binding written `let n := 0`
      is an `int` and stays one; only a literal is untyped.
    - Two fixed widths give the wider.
    """
    if w1 == w2:
        return w1
    if w1 == UNTYPED:
        return w2
    if w2 == UNTYPED:
        return w1
    if w1 == "int" or w2 == "int":
        return "int"
    b1 = _TYPE_BITS.get(w1, 0)
    b2 = _TYPE_BITS.get(w2, 0)
    return w1 if b1 >= b2 else w2


def _int_range(width: str) -> tuple[int, int] | None:
    """Return (min, max) inclusive for a typed integer, or None for 'int'."""
    bits = _TYPE_BITS.get(width)
    if bits is None:
        return None
    if width.startswith("i"):
        return -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    return 0, (1 << bits) - 1


def wrap_int(value: int, width: str) -> int:
    """Wrap an integer value to the range of the given type.

    Unsigned types mask to [0, 2^N-1].
    Signed types mask then sign-extend to [-2^(N-1), 2^(N-1)-1].
    "int" passes through unchanged (arbitrary precision).
    """
    mask = _TYPE_MASK.get(width)
    if mask is None:
        return value
    result = value & mask
    if width.startswith("i"):
        bits = _TYPE_BITS[width]
        if result >= (1 << (bits - 1)):
            result -= (1 << bits)
    return result


def check_int(value: int, width: str) -> int:
    """Check that an integer fits the given type; raise OverflowError if not."""
    r = _int_range(width)
    if r is None:
        return value
    lo, hi = r
    if value < lo or value > hi:
        # Naming the direction is worth the word: an unsigned type is
        # left below far more often than above, and "underflow" says
        # at once that the subtraction went past zero.
        which = "underflow" if value < lo else "overflow"
        raise coded(2279, OverflowError(
            f"integer {which}: {value} does not fit in {width} "
            f"(range {lo}..{hi})"))
    return value


class Value:
    """Base class for all runtime values."""

    __slots__ = ()

    def to_python(self):
        """Convert the value to a corresponding Python object (or raise)."""
        raise TypeError(f"cannot convert {self.__class__.__name__} to Python")

    def __repr__(self):
        return f"{self.__class__.__name__}({self.display()})"


class IntValue(Value):
    """Integer value with a bit-width annotation.

    Supported widths: i1, i8, i16, i32, i64 (signed) and u8, u16, u32, u64 (unsigned).
    The width is mainly metadata at this stage; actual overflow checking
    can be added later.
    """

    __slots__ = ("value", "width")

    def __init__(self, value: int, width: str = "int"):
        self.value = value
        self.width = width

    def display(self):
        return str(self.value)

    def to_python(self):
        return self.value


FLOAT_TYPES: frozenset[str] = frozenset({"f16", "f32", "f64", "bfloat16", "float"})

_FLOAT_STRUCT_FMT: dict[str, str] = {
    "f16": "e",
    "f32": "f",
    "f64": "d",
    "bfloat16": "e",
}


def _float_precision_bits(width: str) -> int:
    return {"f16": 16, "bfloat16": 16, "f32": 32, "f64": 64, "float": 64}[width]


def resolve_float_width(w1: str, w2: str) -> str:
    """The width two floating-point operands settle on.

    A literal states no width, which is recorded as `float` -- the
    arbitrary-precision type it would settle on where nothing else
    says otherwise.  Meeting a sized operand is something else saying
    otherwise, so the literal gives way, as an untyped integer does.
    """
    if w1 == w2:
        return w1
    if w1 == "float":
        return w2
    if w2 == "float":
        return w1
    b1 = _float_precision_bits(w1)
    b2 = _float_precision_bits(w2)
    return w1 if b1 >= b2 else w2


# Significand bits per float type, counting the implicit leading one.
# An integer is exact in the type when it needs no more than these.
_SIGNIFICAND_BITS: dict[str, int] = {
    "f16": 11, "bfloat16": 8, "f32": 24, "f64": 53,
}


def _int_is_exact_in_float(value: int, width: str) -> bool:
    """Whether an integer is representable in a float type without loss.

    An integer is exact when its odd part fits the significand, so
    2**24 and 17000002 are exact in an f32 while 17000001 is not:
    the first two carry a factor of two the exponent can hold, and the
    last needs a twenty-fifth significant bit.
    """
    if width not in _SIGNIFICAND_BITS:
        return True
    try:
        return _clamp_float(float(value), width) == value
    except OverflowError:
        return False


# Exponent and mantissa bits of each floating-point format, from which
# the largest finite value it can hold follows.
_FLOAT_FORMAT: dict[str, tuple[int, int]] = {
    "f16": (5, 10), "bfloat16": (8, 7), "f32": (8, 23), "f64": (11, 52),
}


def float_limits(width: str) -> tuple[float, float] | None:
    """The lowest and largest finite values a float format can hold."""
    fmt = _FLOAT_FORMAT.get(width)
    if fmt is None:
        return None
    exp_bits, mant_bits = fmt
    largest = (2 - 2.0 ** -mant_bits) * 2.0 ** (2 ** (exp_bits - 1) - 1)
    return -largest, largest


def int_limits(width: str) -> tuple[int, int] | None:
    """The lowest and largest values an integer type can hold."""
    return _int_range(width)


def _clamp_float(value: float, width: str) -> float:
    """Round a value to what a float format can represent.

    A value past the top of the format becomes an infinity, which is
    what the format itself answers with.  Whether that is acceptable is
    the caller's question: a sum has nowhere else to go, while a value
    being written down is refused by check_float.
    """
    import struct
    fmt = _FLOAT_STRUCT_FMT.get(width)
    if fmt is None:
        return float(value)
    try:
        if width == "bfloat16":
            as_f32 = struct.pack("f", value)
            truncated = b"\x00\x00" + as_f32[2:]
            return struct.unpack("f", truncated)[0]
        return struct.unpack(fmt, struct.pack(fmt, value))[0]
    except OverflowError:
        return math.inf if value > 0 else -math.inf


def float_overflows(value: float, width: str) -> bool:
    """Whether a number would become an infinity in a float format.

    An infinity that arrives as one is left alone: it is what a float
    answers with when a sum overflows, and every format holds it.  What
    this asks about is a finite number that would stop being one.
    """
    if not math.isfinite(value):
        return False
    return not math.isfinite(_clamp_float(value, _float_check_width(width)))


def _float_check_width(width: str) -> str:
    """The format a value of this width is actually held in.

    An untyped float is arbitrary-precision in the full language.  The
    bootstrap holds it in an f64, so that is what its range is until
    the arbitrary-precision type arrives.
    """
    return "f64" if width == "float" else width


def float_smallest(width: str) -> float | None:
    """The smallest value a float format can tell from zero.

    The smallest subnormal, not the smallest normal one: a subnormal
    is a number the format holds, with fewer significant bits than a
    normal value but not with none.
    """
    fmt = _FLOAT_FORMAT.get(_float_check_width(width))
    if fmt is None:
        return None
    exp_bits, mant_bits = fmt
    return 2.0 ** (2 - 2 ** (exp_bits - 1)) * 2.0 ** -mant_bits


def check_float_arith(value: float, width: str, symbol: str,
                      left: float, right: float, *,
                      may_underflow: bool) -> float:
    """Check what an operation on floats produced against what it means.

    Reported for the reason integer overflow is: the answer would be a
    different number from the one the operation has.  Overflow makes it
    an infinity and underflow makes it a zero, and both are numbers a
    program will go on computing with as though they were the answer.

    A zero from two operands that were not zero can only be a result
    too small for the format to tell from zero, so the check needs no
    knowledge of the exact result to know one was lost.  Addition and
    subtraction ask with may_underflow false: a zero from those is
    exact, since it means the two operands were equal.

    An operand that is already an infinity is left alone.  Nothing was
    lost in an operation whose input was that.
    """
    held = _clamp_float(value, _float_check_width(width))
    if math.isinf(held) and math.isfinite(left) and math.isfinite(right):
        raise coded(2293, OverflowError(
            float_overflow_message(f"{left!r} {symbol} {right!r}", width)))
    if may_underflow and held == 0.0 and left != 0.0 and right != 0.0:
        raise coded(2294, OverflowError(
            float_underflow_message(f"{left!r} {symbol} {right!r}", width)))
    return value


def _float_named_width(width: str) -> str:
    """The width to name in a diagnostic about a value of this width."""
    return "f64" if width == "float" else width


def _float_largest_note(width: str) -> str:
    """The parenthesis naming the largest value a format holds."""
    limits = float_limits(_float_check_width(width))
    return "" if limits is None else f" (largest is {limits[1]!r})"


def float_underflows(value: float, width: str) -> bool:
    """Whether a nonzero number would become a zero in a float format.

    Reaching zero is losing the value; a subnormal is not, being a
    number the format holds with fewer significant bits than a normal
    one.  The caller says what "nonzero" means for what it has: a
    value that is already zero passes, and a literal whose text
    underflowed to zero before it got here is judged by its digits.
    """
    if value == 0.0:
        return False
    return _clamp_float(value, _float_check_width(width)) == 0.0


def check_float(value: float, width: str) -> float:
    """Check that a value stays the number it is in a float format.

    Raises OverflowError when it does not.  Becoming an infinity or a
    zero is not holding the value: either is a different number from
    the one being written down, and finding that out quietly -- from a
    result of inf or 0 much later -- is the outcome worth preventing.
    """
    if float_overflows(value, width):
        raise coded(2293, OverflowError(
            float_overflow_message(repr(value), width)))
    if float_underflows(value, width):
        raise coded(2294, OverflowError(
            float_underflow_message(repr(value), width)))
    return value


def _untyped_width_note(width: str) -> str:
    """Why a diagnostic about an untyped float names f64.

    Nothing in the source said f64.  The bootstrap did, holding an
    untyped float in one until the arbitrary-precision float arrives,
    so it says so rather than naming a type the program never wrote.
    """
    if width != "float":
        return ""
    return (", which is what an untyped float is held in until the "
            "arbitrary-precision float arrives")


def float_overflow_message(written: str, width: str) -> str:
    """What to say about a number a float format cannot hold."""
    return Diagnostic(
           f"float overflow: {written} does not fit in "
           f"{_float_named_width(width)}{_float_largest_note(width)}"
           f"{_untyped_width_note(width)}", 2293)


def float_underflow_message(written: str, width: str) -> str:
    """What to say about a number a float format cannot tell from zero."""
    smallest = float_smallest(width)
    note = "" if smallest is None else f" (smallest is {smallest!r})"
    return Diagnostic(
           f"float underflow: {written} is not zero, but is too small for "
           f"{_float_named_width(width)} to tell from zero{note}"
           f"{_untyped_width_note(width)}", 2294)


class FloatValue(Value):
    """Floating-point value with a width annotation (f16, f32, f64, bfloat16, float)."""

    __slots__ = ("value", "width")

    def __init__(self, value: float, width: str = "float"):
        self.value = value
        self.width = width

    def display(self):
        return repr(self.value)

    def to_python(self):
        return self.value


def mk_float(value: float, width: str = "float") -> "FloatValue":
    return FloatValue(_clamp_float(value, width), width)


class UnitValue(Value):
    """Numeric value with an attached physical unit."""

    __slots__ = ("inner", "unit")

    def __init__(self, inner: Value, unit):
        self.inner = inner
        self.unit = unit

    def display(self):
        return f"{self.inner.display()} {self.unit.display_name}"

    def to_python(self):
        return self.inner.to_python()


_STR_ESCAPES = {
    "\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r",
}


class SyntaxValue(Value):
    """A piece of the program, held rather than run.

    What a macro is handed for each of its arguments and what it
    answers.  `node` is the parse tree; `body` is set instead where the
    piece is a run of statements rather than one expression, since
    those are the two shapes a piece of program comes in.
    """

    __slots__ = ("node", "body")

    def __init__(self, node=None, body=None):
        self.node = node
        self.body = body

    @property
    def is_block(self) -> bool:
        """Whether this is a run of statements rather than an expression."""
        return self.body is not None

    def display(self):
        if self.body is not None:
            return f"⟪{len(self.body)} statements⟫"
        return f"⟪{type(self.node).__name__}⟫"

    def to_python(self):
        return self.node if self.body is None else self.body


class StrValue(Value):
    """String value (UTF-8)."""

    __slots__ = ("value",)

    def __init__(self, value: str):
        self.value = value

    def display(self):
        # Rendered with the language's own quoting rather than Python's
        # repr, which would quote with apostrophes.
        body = "".join(_STR_ESCAPES.get(c, c) for c in self.value)
        return f'"{body}"'

    def to_python(self):
        return self.value


# What a character may hold: a Unicode scalar value.  The surrogates
# are excluded because they are not characters -- they exist to encode
# others in UTF-16, and no UTF-8 text contains one.
MAX_CODE_POINT = 0x10FFFF
_SURROGATES = range(0xD800, 0xE000)


def check_code_point(value: int, where: str, stop: bool = False) -> int:
    """Check that a number names a character, or say why it does not.

    The same question is asked of two different things.  A character
    literal that is not a character is a program the language refuses,
    and the answer is a refusal; `chr` of a number worked out while the
    program runs is a program that ran and could not go on, and the
    answer is a stop.  They leave with different statuses, so the
    caller says which it is asking.
    """
    from interp.errors import ProgramStop
    bad = ProgramStop if stop else TypeError
    if value < 0:
        raise coded(2280, bad(
            f"{where}: {value} is not a code point; a character is "
            f"numbered from 0"))
    if value > MAX_CODE_POINT:
        raise coded(2281, bad(
            f"{where}: {value} is past the last code point, which is "
            f"{MAX_CODE_POINT} (0x10FFFF)"))
    if value in _SURROGATES:
        raise coded(2282, bad(
            f"{where}: {value} is a surrogate, which encodes half of a "
            f"character in UTF-16 rather than being one"))
    return value


class CharValue(Value):
    """A single character: one Unicode scalar value, held as UCS-4.

    A character is not a string of one, and not a number: it is what a
    string is made of, and what iterating one hands over.  It says its
    number with .ord() and an integer makes one with .chr().
    """

    __slots__ = ("code",)

    def __init__(self, code: int):
        self.code = code

    @property
    def char(self) -> str:
        """The character itself, as text."""
        return chr(self.code)

    def display(self):
        # Quoted as a character is written, which is not how a string
        # of one is written: the two are different values.
        body = _CHAR_ESCAPES.get(self.char, self.char)
        return f"'{body}'"

    def to_python(self):
        return self.char


_CHAR_ESCAPES = {
    "\\": "\\\\", "'": "\\'", "\n": "\\n", "\t": "\\t", "\r": "\\r",
}


class BoolValue(Value):
    """Boolean value (distinct from integers)."""

    __slots__ = ("value",)

    def __init__(self, value: bool):
        self.value = value

    def display(self):
        return str(self.value).lower()

    def to_python(self):
        return self.value


class NoneValue(Value):
    """The none value (empty optional)."""

    __slots__ = ()

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def display(self):
        return "\N{EMPTY SET}"

    def to_python(self):
        return None


class SomeValue(Value):
    """An optional value containing a wrapped inner value."""

    __slots__ = ("value",)

    def __init__(self, value: Value):
        self.value = value

    def display(self):
        return f"\N{THERE EXISTS}({self.value.display()})"

    def to_python(self):
        return self.value.to_python()


class ExpectedValue(Value):
    """A result type that holds either a success value or an error value.

    Analogous to Result<T,E> in Rust or std::expected<T,E> in C++.
    Exactly one of ok_value or err_value is set; the other is None.
    """

    __slots__ = ("ok_value", "err_value")

    def __init__(self, ok_value: Value | None = None,
                 err_value: Value | None = None):
        self.ok_value = ok_value
        self.err_value = err_value

    @staticmethod
    def ok(value: Value) -> "ExpectedValue":
        return ExpectedValue(ok_value=value)

    @staticmethod
    def err(error: Value) -> "ExpectedValue":
        return ExpectedValue(err_value=error)

    def is_ok(self) -> bool:
        return self.ok_value is not None

    def is_err(self) -> bool:
        return self.err_value is not None

    def display(self) -> str:
        if self.ok_value is not None:
            return f"ok({self.ok_value.display()})"
        return f"err({self.err_value.display()})"

    def to_python(self):
        if self.ok_value is not None:
            return self.ok_value.to_python()
        raise ValueError(f"expected value contains error: {self.err_value.display()}")


class FuncValue(Value):
    """A user-defined function (closure over an environment)."""

    __slots__ = ("name", "params", "body", "env", "ret_type", "is_replaceable",
                 "pack_param", "param_units", "is_impure", "param_refs",
                 "param_muts", "source_label", "ret_unit", "is_listable",
                 "is_noreturn", "preconditions", "postconditions",
                 "_has_generics", "_param_names", "module", "is_export")

    def __init__(self, name, params, body, env, ret_type=None,
                 is_replaceable: bool = False,
                 pack_param: tuple[str, str | None] | None = None,
                 param_units: dict[str, object] | None = None,
                 is_impure: bool = False,
                 param_refs: set[str] | None = None,
                 param_muts: set[str] | None = None,
                 ret_unit=None,
                 is_listable: bool = False,
                 is_noreturn: bool = False,
                 preconditions: list | None = None,
                 postconditions: list | None = None):
        self.name = name
        self.params = params
        self.body = body
        self.env = env
        self.ret_type = ret_type
        # The unit the return type states, or None where it states none.
        self.ret_unit = ret_unit
        self.is_replaceable = is_replaceable
        self.pack_param = pack_param
        self.param_units: dict[str, object] = param_units or {}
        self.is_impure = is_impure
        self.param_refs: set[str] = param_refs or set()
        self.param_muts: set[str] = param_muts or set()
        # Whether the function is threaded over an argument that is
        # deeper than the parameter asks for.
        self.is_listable = is_listable
        # Whether the function hands control back at all.
        self.is_noreturn = is_noreturn
        # What the function holds to on the way in and on the way out.
        self.preconditions = preconditions or []
        self.postconditions = postconditions or []
        # Two things about the signature that a call would otherwise
        # work out again every time it is made.  They depend on the
        # function alone, so the first call settles them and the rest
        # read them; None means not yet asked.  Whether the signature
        # mentions a generic is decided in the evaluator, which is
        # where the type predicates live.
        self._has_generics: bool | None = None
        self._param_names: frozenset | None = None
        # The module the definition was written in, and whether it is
        # exported from it.  Both are settled where it is installed.
        self.module: str = ""
        self.is_export: bool = False
        # Where the body was written.  None means the file the program
        # was loaded from; the REPL sets it to the entry that defined the
        # function, since each entry has its own line numbering.
        self.source_label: str | None = None


class LambdaValue(Value):
    """An anonymous function with explicit capture list.

    Also used internally to represent curried (partially-applied) functions.
    When partial_func is set, calling the lambda prepends partial_args to
    the new arguments and invokes the original function.
    """

    __slots__ = ("params", "body", "env", "captures",
                 "ret_type", "partial_func", "partial_args")

    def __init__(self, params, body, env, captures=None,
                 ret_type=None, partial_func=None, partial_args=None):
        self.params = params
        self.body = body
        self.env = env
        self.captures = captures
        self.ret_type = ret_type
        self.partial_func = partial_func
        self.partial_args = partial_args or []

    def display(self):
        if self.partial_func is not None:
            applied = ", ".join(a.display() for a in self.partial_args)
            remaining = ", ".join(p[0] for p in self.params)
            return f"\N{GREEK SMALL LETTER LAMDA}{remaining} (partial {self.partial_func.name}[{applied}])"
        params = ", ".join(p[0] for p in self.params)
        if self.captures:
            caps = ", ".join(self.captures)
            return f"\N{GREEK SMALL LETTER LAMDA}{params} |{caps}|"
        return f"\N{GREEK SMALL LETTER LAMDA}{params}"


class BuiltinFunc(Value):
    """A built-in function implemented in Python."""

    __slots__ = ("name", "arity", "func", "is_listable")

    def __init__(self, name, arity, func, is_listable=False):
        """
        Args:
            name: the function's name in the language namespace.
            arity: expected number of arguments (-1 for variadic).
            func: callable(values) -> Value where values is a list of Value args.
            is_listable: whether a container argument is taken apart and
                the function asked of each element, as @listable has it.
        """
        self.name = name
        self.arity = arity
        self.func = func
        self.is_listable = is_listable

    def display(self):
        return f"<builtin {self.name}>"


class ObjectValue(Value):
    """Wraps an arbitrary Python object as a runtime value.

    Used to pass language-level objects (DirFD, Allocator, File) through
    the evaluation system while preserving their methods.
    """

    __slots__ = ("obj",)

    def __init__(self, obj):
        self.obj = obj

    def display(self):
        # Wrapped objects that can describe themselves do so; the rest
        # fall back to their type name.
        shown = getattr(self.obj, "display", None)
        if callable(shown):
            return shown()
        return f"<{type(self.obj).__name__}>"


class BuiltinBoundMethod(Value):
    """A bound method on a Python object (exposed to NGPL)."""

    __slots__ = ("obj", "method_name")

    def __init__(self, obj, method_name: str):
        self.obj = obj
        self.method_name = method_name

    def display(self):
        return f"<bound {self.method_name}>"

    def __call__(self, args):
        meth = getattr(self.obj, self.method_name)
        return meth(*args)


class TupleValue(Value):
    """An immutable tuple of runtime Values, used by foreach with multiple iterables."""

    __slots__ = ("elements",)

    def __init__(self, elements: list["Value"]):
        self.elements = elements

    def get(self, index: int) -> "Value":
        if 0 <= index < len(self.elements):
            return self.elements[index]
        raise IndexError(f"tuple index {index} out of range (length {len(self.elements)})")

    def display(self):
        return "(" + ", ".join(e.display() for e in self.elements) + ")"

    def to_python(self):
        return tuple(e.to_python() for e in self.elements)


class EnumType(Value):
    """Runtime representation of an enum type definition.

    Holds the mapping from member names to integer values and the reverse.
    For @flag enums, binary logic operations (|, &, ^, ~) combine values.
    """

    __slots__ = ("name", "underlying_type", "is_flag",
                 "members", "values_to_names")

    def __init__(self, name: str, underlying_type: str | None,
                 members: dict[str, int], is_flag: bool = False):
        self.name = name
        self.underlying_type = underlying_type or "u64"
        self.is_flag = is_flag
        self.members = members
        self.values_to_names: dict[int, str] = {v: k for k, v in members.items()}

    def display(self):
        return f"<enum {self.name}>"


class EnumValue(Value):
    """A runtime value of an enum type."""

    __slots__ = ("enum_type", "value")

    def __init__(self, enum_type: EnumType, value: int):
        self.enum_type = enum_type
        self.value = value

    def display(self) -> str:
        name = self.enum_type.values_to_names.get(self.value)
        if name is not None:
            return f"{self.enum_type.name}.{name}"
        if self.enum_type.is_flag and self.value != 0:
            parts = []
            remaining = self.value
            for member_name, member_val in sorted(
                    self.enum_type.members.items(), key=lambda x: x[1], reverse=True):
                if member_val != 0 and (remaining & member_val) == member_val:
                    parts.append(f"{self.enum_type.name}.{member_name}")
                    remaining &= ~member_val
            if remaining == 0 and parts:
                return " | ".join(reversed(parts))
        return f"{self.enum_type.name}({self.value})"

    def to_python(self):
        return self.value


class StructType(Value):
    """Runtime representation of a struct (product type) definition.

    repr_kind holds the layout attribute given by @repr(...), or None
    when the struct has no defined layout and the implementation is free
    to order and pad its fields as it sees fit.
    """

    __slots__ = ("name", "fields", "methods", "repr_kind",
                 "_ref_self_methods", "field_units", "_resolved_units")

    def __init__(self, name: str, fields: list[tuple[str, str]],
                 methods: dict[str, "FuncValue"] | None = None,
                 repr_kind: str | None = None, field_units=None):
        self.name = name
        self.fields = fields
        self.methods: dict[str, FuncValue] = methods or {}
        self.repr_kind = repr_kind
        self._ref_self_methods: set[str] = set()
        # The unit specs the definition wrote per field, resolved to
        # Unit objects on first use -- the units a file defines for
        # itself register after the structs do.
        self.field_units = field_units or {}
        self._resolved_units: dict = {}

    def field_unit(self, name: str):
        """The Unit a field's numbers count in, or None."""
        if name in self._resolved_units:
            return self._resolved_units[name]
        spec = self.field_units.get(name)
        unit = None
        if spec is not None:
            from interp.units import eval_unit_formula
            unit = eval_unit_formula(spec)
        self._resolved_units[name] = unit
        return unit

    def display(self):
        if self.repr_kind is not None:
            return f"<struct {self.name} @repr({self.repr_kind})>"
        return f"<struct {self.name}>"


class StructInstance:
    """An instance of a struct (product type), wrapped in ObjectValue."""

    def __init__(self, struct_type: StructType, field_values: dict[str, Value]):
        self.struct_type = struct_type
        self.field_values = field_values

    def display(self) -> str:
        fields = ", ".join(
            f"{k}: {v.display()}" for k, v in self.field_values.items())
        return f"{self.struct_type.name} {{ {fields} }}"


class RangeValue(Value):
    """A range value representing start…end or start…step…end (inclusive)."""

    __slots__ = ("start", "end", "step")

    def __init__(self, start: int, end: int, step: int | None = None):
        self.start = start
        self.end = end
        self.step = step

    def to_list(self) -> list[int]:
        """Expand the range to a list of integers."""
        if self.step is not None:
            if self.step == 0:
                from interp.errors import ProgramStop
                raise ProgramStop("range step must not be zero")
            if self.step > 0:
                return list(range(self.start, self.end + 1, self.step))
            return list(range(self.start, self.end - 1, self.step))
        if self.start <= self.end:
            return list(range(self.start, self.end + 1))
        return list(range(self.start, self.end - 1, -1))

    @property
    def size(self) -> int:
        return len(self.to_list())

    def display(self):
        if self.step is not None:
            return f"{self.start}\N{HORIZONTAL ELLIPSIS}{self.step}\N{HORIZONTAL ELLIPSIS}{self.end}"
        return f"{self.start}\N{HORIZONTAL ELLIPSIS}{self.end}"

    def to_python(self):
        return self.to_list()


MAX_TENSOR_RANK: int = 8


@_functools.lru_cache(maxsize=None)
def parse_container_type(type_name: str):
    """Take `std.dict(K,V)` or `std.set(V)` apart, or answer None.

    The inverse of how a program writes them, and the one place the
    spelling is read, so nothing else has to know it.
    """
    if not isinstance(type_name, str) or not type_name.endswith(")"):
        return None
    for kind, want in (("std.dict", 2), ("std.set", 1)):
        head = kind + "("
        if not type_name.startswith(head):
            continue
        inside = type_name[len(head):-1]
        args, depth, current = [], 0, ""
        for ch in inside:
            if ch == "," and depth == 0:
                args.append(current.strip())
                current = ""
                continue
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            current += ch
        if current.strip():
            args.append(current.strip())
        if len(args) != want:
            return None
        return (kind, args)
    return None


def hash_key(value: "Value"):
    """What a value is remembered by, or None where it cannot be one.

    A key has to be a thing that is the same thing every time it is
    asked about, so what may be one is what the language compares
    exactly: a number, a character, a string, a truth value.  A
    measured number is remembered by what it measures as well as by how
    much, since a metre and a second are not the same key.
    """
    inner = value.value if isinstance(value, SomeValue) else value
    unit = None
    if isinstance(inner, UnitValue):
        unit, inner = inner.unit.display_name, inner.inner
    if isinstance(inner, IntValue):
        return ("int", inner.value, unit)
    if isinstance(inner, StrValue):
        return ("str", inner.value, unit)
    if isinstance(inner, CharValue):
        return ("char", inner.char, unit)
    if isinstance(inner, BoolValue):
        return ("bool", inner.value, unit)
    if isinstance(inner, EnumValue):
        return ("enum", inner.enum_type.name, inner.value)
    return None


class HashValue:
    """A mapping from keys to values, kept in the order they arrived.

    One type of key and one type of value, as an array holds one type
    of element: what a container holds is what its type says, and a
    type that said "some of these and some of those" would say nothing.

    The order is the order things were put in.  A hash has no order of
    its own, and walking one in whatever order the implementation
    happens to use makes a program's output depend on something nobody
    wrote down.
    """

    __slots__ = ("entries", "key_type", "value_type")

    def __init__(self, entries=None, key_type=None, value_type=None):
        # key -> (key value, value), keyed by what hash_key answers.
        self.entries: dict = dict(entries) if entries else {}
        self.key_type = key_type
        self.value_type = value_type

    @property
    def sizeof(self) -> int:
        return len(self.entries)

    def get(self, key: "Value"):
        found = self.entries.get(hash_key(key))
        return None if found is None else found[1]

    def has(self, key: "Value") -> bool:
        return hash_key(key) in self.entries

    def put(self, key: "Value", value: "Value"):
        self.entries[hash_key(key)] = (key, value)

    def drop(self, key: "Value") -> bool:
        return self.entries.pop(hash_key(key), None) is not None

    def keys(self) -> list:
        return [k for k, _ in self.entries.values()]

    def values(self) -> list:
        return [v for _, v in self.entries.values()]

    def pairs(self) -> list:
        return list(self.entries.values())

    def display(self) -> str:
        if not self.entries:
            return "\N{LEFT DOUBLE PARENTHESIS}\N{RIGHT DOUBLE PARENTHESIS}"
        inside = ", ".join(f"{k.display()}: {v.display()}"
                           for k, v in self.entries.values())
        return (f"\N{LEFT DOUBLE PARENTHESIS}{inside}"
                f"\N{RIGHT DOUBLE PARENTHESIS}")


class SetValue:
    """The values that are in it, kept in the order they arrived.

    One type of value, and each of them once.  Everything said about a
    dictionary's keys is said about these, a set being a dictionary that answers
    only whether.
    """

    __slots__ = ("entries", "value_type")

    def __init__(self, entries=None, value_type=None):
        self.entries: dict = dict(entries) if entries else {}
        self.value_type = value_type

    @property
    def sizeof(self) -> int:
        return len(self.entries)

    def has(self, value: "Value") -> bool:
        return hash_key(value) in self.entries

    def put(self, value: "Value"):
        self.entries[hash_key(value)] = value

    def drop(self, value: "Value") -> bool:
        return self.entries.pop(hash_key(value), None) is not None

    def values(self) -> list:
        return list(self.entries.values())

    def display(self) -> str:
        if not self.entries:
            return "\N{LEFT DOUBLE PARENTHESIS}\N{RIGHT DOUBLE PARENTHESIS}"
        inside = ", ".join(v.display() for v in self.entries.values())
        return (f"\N{LEFT DOUBLE PARENTHESIS}{inside}"
                f"\N{RIGHT DOUBLE PARENTHESIS}")


class ArrayValue(Value):
    """A mutable array of runtime Values with bounds checking.

    Elements can be read via get() and written via set().
    Both raise IndexError for out-of-bounds access.
    If element_type is set, stored values are automatically coerced.

    When _backing is set, the array is a view into a shared list
    at the given offset/length.  Reads and writes go through the backing.
    """

    __slots__ = ("elements", "element_type", "element_unit", "fixed_size",
                 "_backing", "_offset", "_length")

    def __init__(self, elements=None, element_type: str | None = None,
                 *, backing: list | None = None, offset: int = 0,
                 length: int | None = None, fixed_size: int | None = None,
                 element_unit=None):
        if backing is not None:
            self._backing = backing
            self._offset = offset
            self._length = length if length is not None else len(backing) - offset
            self.elements = None
        else:
            self._backing = None
            self._offset = 0
            self._length = 0
            self.elements = list(elements) if elements else []
        self.element_type = element_type
        # What each element measures.  Read off the first element where
        # it is not stated, so an array built by slicing, joining or
        # threading answers for what it actually holds without every
        # one of those places having to say so.
        if element_unit is None:
            first = self.get(0) if self.sizeof else None
            if isinstance(first, UnitValue):
                element_unit = first.unit
        self.element_unit = element_unit
        # Set when the array's type names a length, as in i32[4].  Such
        # an array has that many elements for as long as it exists.
        self.fixed_size = fixed_size

    def get(self, index: int) -> Value:
        """Return element at index; raises IndexError if out of range."""
        n = self.sizeof
        if 0 <= index < n:
            if self._backing is not None:
                return self._backing[self._offset + index]
            return self.elements[index]
        raise coded(2758, IndexError(
            f"array index {index} out of range (length {n})"))

    @property
    def sizeof(self) -> int:
        if self._backing is not None:
            return self._length
        return len(self.elements)

    def values(self) -> list[Value]:
        """Return the elements as a plain list.

        A view has no `elements` list of its own, so anything wanting
        to walk an array has to come through here rather than reading
        the attribute, which is None for a view.
        """
        if self._backing is not None:
            return self._backing[self._offset:self._offset + self._length]
        return list(self.elements)

    def set(self, index: int, value: Value):
        """Set element at index; raises IndexError if out of range."""
        value = self._checked(value)
        n = self.sizeof
        if index < 0 or index >= n:
            raise coded(2759, IndexError(
                f"array index {index} out of range (length {n})"))
        if self._backing is not None:
            self._backing[self._offset + index] = value
        else:
            self.elements[index] = value

    def _checked(self, value: Value) -> Value:
        """Measure a value against what this array holds, before storing it.

        An array says one type and one unit for everything in it, so
        every way a value gets in -- a subscript, a push, an insert --
        asks the same question.  Where nothing was declared the first
        element answers instead: that is what the array in fact holds,
        and it is the only thing a value can be measured against.
        """
        held = self.element_type
        unit = self.element_unit
        if held is None and unit is None and self.sizeof:
            first = self.get(0)
            inner = first.inner if isinstance(first, UnitValue) else first
            unit = first.unit if isinstance(first, UnitValue) else None
            if isinstance(inner, (IntValue, FloatValue, StrValue,
                                  CharValue, BoolValue)):
                held = runtime_type_of(inner)
                if is_unwidthed(held):
                    held = None
        if unit is None and isinstance(value, UnitValue):
            raise coded(2324, TypeError(
                f"an array of {held or 'unmeasured numbers'} cannot hold "
                f"{value.unit.display_name}; use @dropunit to part with it"))
        if unit is not None and not isinstance(value, UnitValue):
            raise coded(2325, TypeError(
                f"an array measured in {unit.display_name} cannot hold a "
                f"number that measures nothing"))
        if held is None:
            return apply_unit(value, unit) if unit is not None else value
        mismatch = _scalar_kind_mismatch(
            value.inner if isinstance(value, UnitValue) else value, held)
        if mismatch is not None:
            raise coded(2760, TypeError(
                f"an array of {held} cannot hold {mismatch}"))
        return coerce_to_type(value, held, unit)

    def _check_resizable(self, op: str):
        """Reject an operation that would change the array's length.

        A view borrows a window into another array's storage, so it has
        no length of its own to change: growing or shrinking it would
        have to move the elements the owner still refers to.

        A fixed-size array has its length in its type, which is what
        lets a reader know how much is there without tracing where it
        came from.  Resizing one would make the type a lie.
        """
        if self._backing is not None:
            raise TypeError(f"{op}: cannot resize a view into another array")
        if self.fixed_size is not None:
            raise coded(2761, TypeError(
                f"{op}: cannot resize a fixed-size array; its type says it "
                f"holds {self.fixed_size} element"
                f"{'' if self.fixed_size == 1 else 's'}"))

    def push(self, value: Value):
        """Append a value to the end of the array."""
        self._check_resizable("push")
        self.elements.append(self._checked(value))

    def pop(self) -> Value | None:
        """Remove and return the last element, or None when empty."""
        self._check_resizable("pop")
        if not self.elements:
            return None
        return self.elements.pop()

    def insert(self, index: int, value: Value):
        """Insert a value at index, shifting later elements right.

        The index may equal the length, which appends.
        """
        self._check_resizable("insert")
        n = len(self.elements)
        if index < 0 or index > n:
            raise coded(2762, IndexError(
                f"insert index {index} out of range (length {n})"))
        self.elements.insert(index, self._checked(value))

    def remove(self, index: int) -> Value:
        """Remove and return the element at index, shifting later ones left."""
        self._check_resizable("remove")
        n = len(self.elements)
        if index < 0 or index >= n:
            raise coded(2763, IndexError(
                f"remove index {index} out of range (length {n})"))
        return self.elements.pop(index)

    def display(self) -> str:
        """Render the array using the language's own literal syntax."""
        return "[" + ", ".join(self.get(i).display()
                               for i in range(self.sizeof)) + "]"


class Iterator(Value):
    """A source of successive values.

    The whole protocol is next(): it returns the next value, or ∅ when
    there are none left.  An iterator is obtained from a container with
    iterate(), and holds whatever position it needs to resume from.

    A produced value is marked present, so that testing an iterator's
    result in a boolean context asks whether there was a value at all
    rather than whether that value was itself truthy -- an element of 0
    or "" ends no loop.  It also lets an iterator carry ∅ as an ordinary
    value without that being mistaken for the end.
    """

    __slots__ = ()

    def next(self) -> "Value":
        raise NotImplementedError

    def display(self):
        return "<iterator>"


class ArrayIterator(Iterator):
    """Walks an array's elements in order."""

    __slots__ = ("array", "index")

    def __init__(self, array: "ArrayValue"):
        self.array = array
        self.index = 0

    def next(self) -> "Value":
        if self.index >= self.array.sizeof:
            return NoneValue()
        index = self.index
        self.index += 1
        # A reference rather than a copy, so a mutable loop binding can
        # write the element back.  Reading one yields the element, so an
        # ordinary loop cannot tell the difference.
        return SomeValue(ElementRef(self.array, index))

    def display(self):
        return f"<array iterator at {self.index}>"


class Reference(Value):
    """A place that can be read through and written through.

    Reading a name bound to a reference yields the referent, and
    assigning to that name writes through to wherever the reference
    points rather than rebinding the name.
    """

    __slots__ = ()

    def get(self) -> "Value":
        raise NotImplementedError

    def set(self, value: "Value"):
        raise NotImplementedError


class RefValue(Reference):
    """A mutable reference to a binding in a specific environment frame.

    When passed to a function parameter declared with &type, modifications
    to the parameter inside the function are visible to the caller.
    """

    __slots__ = ("env", "name")

    def __init__(self, env, name: str):
        self.env = env
        self.name = name

    def get(self) -> "Value":
        return self.env.lookup(self.name)

    def set(self, value: "Value"):
        self.env.assign(self.name, value)

    def display(self):
        return f"&{self.name}"


class ElementRef(Reference):
    """A reference to one element of an array.

    Produced by iterating an array with & or &mut.  Both forms refer to
    the element rather than copying it; only the mutable form may be
    written through, so that assigning to the loop variable writes into
    the array.
    """

    __slots__ = ("array", "index", "is_mut")

    def __init__(self, array: "ArrayValue", index: int, is_mut: bool = True):
        self.array = array
        self.index = index
        self.is_mut = is_mut

    def get(self) -> "Value":
        return self.array.get(self.index)

    def set(self, value: "Value"):
        # The loop variable is frozen, so this is a backstop rather than
        # the diagnostic a program normally sees.
        if not self.is_mut:
            raise TypeError("cannot write through a shared borrow")
        self.array.set(self.index, value)

    def display(self):
        prefix = "&mut " if self.is_mut else "&"
        return f"{prefix}{self.get().display()}"


def deep_copy_value(v: Value) -> Value:
    """Create a deep copy of a value, duplicating arrays."""
    if isinstance(v, ObjectValue) and isinstance(v.obj, ArrayValue):
        arr = v.obj
        if arr._backing is not None:
            elems = [arr.get(i) for i in range(arr.sizeof)]
        else:
            elems = list(arr.elements)
        # A copy of a fixed-size array is still fixed-size: the length
        # is part of the type, and copying does not change the type.
        return ObjectValue(ArrayValue(elems, arr.element_type,
                                      fixed_size=arr.fixed_size))
    return v


class TypeValue(Value):
    """A reified type, produced by @typeof and @resultof.

    Supports equality comparison so it can be used with static_assert_eq.
    """

    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name

    def display(self):
        return self.name

    def to_python(self):
        return self.name


class UnitOfValue(Value):
    """A reified unit, produced by @unitof and standalone ¤unit references.

    Supports equality comparison so it can be used with static_assert_eq.
    """

    __slots__ = ("unit",)

    def __init__(self, unit):
        self.unit = unit

    def display(self):
        if self.unit is None:
            return "dimensionless"
        return self.unit.display_name

    def to_python(self):
        return self.display()


def _is_unsigned(width: str) -> bool:
    """Return True if width names an unsigned integer type."""
    return width.startswith("u") or width in ("byte", "usize")


def mk_int(value: int, width: str = "int") -> IntValue:
    """Create an IntValue, reporting a result its type cannot hold.

    A width is what a program says a value stays inside, so leaving
    that range is a mistake to report rather than a number to adjust —
    for an unsigned type as much as a signed one.  Wrapping is what
    @wrap asks for, and mk_int_wrap is what it uses.

    Untyped `int` has arbitrary precision and no range to leave.
    """
    if -1 <= value <= 256:
        got = _SMALL_INTS.get((value, width))
        if got is not None:
            return got
        made = IntValue(check_int(value, width), width)
        _SMALL_INTS[(value, width)] = made
        return made
    return IntValue(check_int(value, width), width)


_SMALL_INTS: dict = {}


def mk_int_wrap(value: int, width: str = "int") -> IntValue:
    """Create an IntValue, wrapping to the type's range (for bitwise ops)."""
    return IntValue(wrap_int(value, width), width)


def mk_str(value):
    """Create a StrValue."""
    return StrValue(value)


def mk_bool(value):
    """The BoolValue for a truth: two of them serve every answer."""
    return TRUE_VALUE if value else FALSE_VALUE


TRUE_VALUE = BoolValue(True)
FALSE_VALUE = BoolValue(False)


# The one ∅ every answer that has none hands back.
_NONE_VALUE = NoneValue()


def none():
    """Get the singleton NoneValue."""
    return _NONE_VALUE


def some(value):
    """Wrap a value in SomeValue."""
    return SomeValue(value)


def is_none(value):
    """Check if a value is the none (empty optional)."""
    return isinstance(value, NoneValue)


def is_some(value):
    """Check if a value is wrapped in SomeValue."""
    return isinstance(value, SomeValue)


def is_expected_err(value):
    """Check if a value is an ExpectedValue holding an error."""
    return isinstance(value, ExpectedValue) and value.is_err()


@_functools.lru_cache(maxsize=None)
def _split_optional_type(type_name: str) -> tuple[str, str | None]:
    """Split a type string into base type and optional/expected error type.

    Returns (base, None) for plain types, (base, "") for T? optionals,
    (base, error_type) for T?E expected types.
    """
    qpos = type_name.find("?")
    if qpos < 0:
        return type_name, None
    return type_name[:qpos], type_name[qpos + 1:]


@_functools.lru_cache(maxsize=None)
def is_generic_type(type_str: str) -> bool:
    """Return True if type_str contains a generic type parameter (name ending with ')."""
    base = type_str
    qpos = base.find("?")
    if qpos >= 0:
        base = base[:qpos]
    if base.endswith("[]"):
        base = base[:-2]
    return base.endswith("\N{APOSTROPHE}") and len(base) > 1


def runtime_type_of(value: "Value") -> str:
    """Get the runtime type name of a value for generic type resolution."""
    if isinstance(value, UnitValue):
        return runtime_type_of(value.inner)
    if isinstance(value, SomeValue):
        return runtime_type_of(value.value)
    if isinstance(value, IntValue):
        return "int" if value.width == UNTYPED else value.width
    if isinstance(value, FloatValue):
        return value.width
    if isinstance(value, StrValue):
        return "str"
    if isinstance(value, CharValue):
        return "char"
    if isinstance(value, BoolValue):
        return "bool"
    if isinstance(value, NoneValue):
        return "\N{EMPTY SET}"
    if isinstance(value, ObjectValue):
        if isinstance(value.obj, StructInstance):
            return value.obj.struct_type.name
        if isinstance(value.obj, ArrayValue):
            et = value.obj.element_type or "int"
            return et + "[]"
        if isinstance(value.obj, HashValue):
            held = value.obj
            return (f"std.dict({held.key_type or '?'},"
                    f"{held.value_type or '?'})")
        if isinstance(value.obj, SetValue):
            return f"std.set({value.obj.value_type or '?'})"
        # Something the runtime holds that a program cannot write a
        # type for -- a file, a directory, an arena.  It answers with
        # what it is rather than with "int", which was a lie wherever
        # this reached a diagnostic.
        return type(value.obj).__name__
    if isinstance(value, EnumValue):
        return value.enum_type.name
    if isinstance(value, TupleValue):
        # Written the way the type is, so a value that answers about
        # itself answers something a program could write down.
        return "(" + ", ".join(runtime_type_of(e)
                               for e in value.elements) + ")"
    if isinstance(value, TypeValue):
        return "type"
    if isinstance(value, (FuncValue, LambdaValue, BuiltinFunc,
                          BuiltinBoundMethod)):
        return "fn"
    return "int"


_TYPE_ALIASES: dict[str, str] = {}
_USER_TYPES: set[str] = set()


def is_type_name(name: str) -> bool:
    """Whether a name names a type rather than something a program binds.

    A type name is reserved: it names a type wherever it appears, and
    no definition may take it for a variable, a parameter, or a
    function.
    """
    return (name in BUILTIN_TYPES or name in FAST_TYPES
            or name in _USER_TYPES or name in _TYPE_ALIASES
            or _parse_int_width(name) is not None)


# Struct names, so that a parameter or binding naming one can be held
# to it the way an enum or a sum type is.
_STRUCT_TYPES: set[str] = set()


def register_struct_type(name: str):
    """Register a struct's name as a type that may be written down."""
    _STRUCT_TYPES.add(name)
    _USER_TYPES.add(name)
    _clear_type_memos()


def is_struct_type(name: str) -> bool:
    """Whether a type name names a struct."""
    return name in _STRUCT_TYPES


def struct_type_admits(name: str, value: "Value") -> bool:
    """Whether a value is an instance of the named struct."""
    inner = value.value if isinstance(value, SomeValue) else value
    return (isinstance(inner, ObjectValue)
            and isinstance(inner.obj, StructInstance)
            and inner.obj.struct_type.name == name)


def register_user_type(name: str):
    """Register a user-defined type name (struct, etc.)."""
    _USER_TYPES.add(name)
    _clear_type_memos()


def register_type_alias(name: str, target: str):
    """Register a user-defined type alias."""
    _TYPE_ALIASES[name] = target
    _clear_type_memos()


# Enum type names, so that a type written in a signature can be
# recognized as one without reaching for the environment.
# Each enum's name, mapped to the integer type its values are stored
# in.  None where the enum did not say, which C spells `int`.
_ENUM_TYPES: dict[str, str | None] = {}


def register_enum_type(name: str, underlying: str | None = None, obj=None):
    """Register an enum's name as a type that may be written down."""
    _ENUM_TYPES[name] = underlying
    if obj is not None:
        _ENUM_OBJECTS[name] = obj
    _USER_TYPES.add(name)
    _clear_type_memos()


def enum_object(name: str):
    """The enum of that name, or None where the name is not one."""
    return _ENUM_OBJECTS.get(name)


def enum_admit(name: str, value: "Value") -> "Value":
    """What an enum-typed target accepts.

    A value of the enum passes.  A normal enum is exhaustive: it holds
    exactly its members, so a number that is one member's value becomes
    that member, and any other number is refused by name.  A @flag
    enum's values are combinations of its members, which a bare number
    does not name, so a number is refused there as it always was.
    """
    if isinstance(value, EnumValue) and value.enum_type.name == name:
        return value
    et = _ENUM_OBJECTS.get(name)
    if (et is not None and isinstance(value, IntValue)
            and not isinstance(value, UnitValue)):
        if et.is_flag:
            # The same reason the comparison gives, said in the same
            # words: a flag enum's values are combinations, and no bare
            # number names one.
            raise coded(2827, TypeError(
                f"'{name}' is a @flag enum, so its values are combinations "
                f"of members that a bare number does not name"))
        if value.value in et.values_to_names:
            return EnumValue(et, value.value)
        raise coded(2828, TypeError(
            f"'{name}' holds exactly its members, and {value.value} is "
            f"not one of them"))
    raise coded(2829, TypeError(
        f"'{name}' is an enum, but the value is {runtime_type_of(value)}"))


def is_enum_type(name: str) -> bool:
    """Whether a type name names an enum."""
    return name in _ENUM_TYPES


def enum_underlying_type(name: str) -> str | None:
    """The integer type an enum's values are stored in.

    An enum that names no type stores its values in u64: the widest
    unsigned type covers every auto-numbered and flag member, and the
    bootstrap has no `int` to fall back on, so one answer serves both
    languages.  A member that wants to be negative names a signed
    underlying type.
    """
    underlying = _ENUM_TYPES.get(name)
    if underlying is None or underlying == "int":
        return "u64"
    return underlying


# The enum type objects themselves, so a number meeting an enum-typed
# target can be measured against the members.
_ENUM_OBJECTS: dict[str, "EnumType"] = {}

# Sum types, by name, each holding the alternatives it admits.
_SUM_TYPES: dict[str, list[str]] = {}


def register_sum_type(name: str, alternatives: list[str]):
    """Register `type NAME = A | B` and the alternatives it admits."""
    _SUM_TYPES[name] = list(alternatives)
    _USER_TYPES.add(name)


def sum_type_alternatives(name: str) -> list[str] | None:
    """Return the alternatives of a sum type, or None if not one."""
    return _SUM_TYPES.get(name)


def a_sum_holds_both(one: str, other: str) -> bool:
    """Whether some declared sum type has both of these among its own.

    Two types that disagree are a mistake wherever one value is wanted
    -- unless a sum type says the two belong together, which is what a
    sum type is for.  Asked of every one declared, since what is being
    looked at is a value whose written type is not in hand.
    """
    return any(one in alternatives and other in alternatives
               for alternatives in _SUM_TYPES.values())


def sum_type_admits(name: str, value: "Value") -> bool:
    """Whether a value is one of a sum type's alternatives."""
    alternatives = _SUM_TYPES.get(name)
    if alternatives is None:
        return False
    return runtime_type_of(value) in alternatives


def sum_type_settle(name: str, value: "Value") -> "Value":
    """Bring a value to whichever alternative of a sum type it belongs to.

    A value that already has one of the alternatives' types is that
    alternative.  An untyped number does not, so it settles on the one
    alternative that can hold it, the way it would settle on a
    parameter's type.  Where more than one could, the program has to
    say which it meant.

    Returns the value under its alternative, or raises TypeError.
    """
    alternatives = _SUM_TYPES[name]
    actual = runtime_type_of(value)
    if actual in alternatives:
        return value

    # Only an untyped number is open to settling; anything else has a
    # type of its own already and simply is not one of these.
    untyped_int = isinstance(value, IntValue) and is_unwidthed(value.width)
    untyped_float = isinstance(value, FloatValue) and value.width == "float"
    if untyped_int or untyped_float:
        family = FLOAT_TYPES if untyped_float else _TYPE_BITS
        candidates = []
        for alt in alternatives:
            if alt not in family:
                continue
            try:
                # coerce_to_type carries integers to their width but
                # leaves a float as it found it, so a float alternative
                # is built directly.
                settled = (mk_float(value.value, alt) if untyped_float
                           else coerce_to_type(value, alt))
            except (TypeError, OverflowError):
                continue
            candidates.append((alt, settled))
        if len(candidates) == 1:
            return candidates[0][1]
        if len(candidates) > 1:
            raise TypeError(
                f"'{name}' is {' | '.join(alternatives)}, and this value "
                f"could be {' or '.join(a for a, _ in candidates)}; "
                f"write the type meant")

    raise coded(2271, TypeError(
        f"'{name}' is {' | '.join(alternatives)}, "
        f"but the value is {actual}"))


_type_memo: dict = {}
_alias_memo: dict = {}


def _clear_type_memos() -> None:
    _type_memo.clear()
    _alias_memo.clear()


def resolve_type_alias(type_name: str) -> str:
    got = _alias_memo.get(type_name)
    if got is not None:
        return got
    resolved = _resolve_type_alias_uncached(type_name)
    _alias_memo[type_name] = resolved
    return resolved


def _resolve_type_alias_uncached(type_name: str) -> str:
    """Resolve type aliases transitively, returning the underlying type."""
    seen: set[str] = set()
    while type_name in _TYPE_ALIASES and type_name not in seen:
        seen.add(type_name)
        type_name = _TYPE_ALIASES[type_name]
    return type_name


_ARRAY_TYPE_RE = re.compile(r"(\w+(?:\.\w+)*|\(.*\))\[(\d*(?:,\d*)*)\]")


@_functools.lru_cache(maxsize=None)
def _parse_array_type(type_name: str) -> tuple[str, list[int | None]] | None:
    """Parse an array type string.

    Returns (element_type, dims), where dims has one entry per
    dimension: an int where the type fixes that dimension, None where
    it leaves it open.  `i32[]` is one open dimension, `i32[2,3]` two
    fixed ones, `i32[,3]` an open one over a fixed one.
    """
    # An element type is a name or a tuple, and a tuple carries commas
    # and brackets of its own, so it is matched as a parenthesized run
    # rather than as a word.  A dotted name -- std.iovec -- is one name
    # for this purpose, since the dot belongs to the type and not to
    # the array written around it.
    m = _ARRAY_TYPE_RE.fullmatch(type_name)
    if m is None:
        return None
    return m.group(1), [int(d) if d else None for d in m.group(2).split(",")]


def array_type_mismatch(value: "Value", type_name: str) -> str | None:
    """Say how an array value differs from a type that names no array.

    The brackets are what a type says an array with, so a type without
    them names a scalar.  An array meeting one is not a shorthand for
    what its elements are; it is a value the type does not describe.

    Returns the explanation, or None where there is nothing to object
    to — the value is not an array, or the type says it is one.
    """
    if not (isinstance(value, ObjectValue) and isinstance(value.obj, ArrayValue)):
        return None
    if _parse_array_type(type_name) is not None:
        return None
    arr = value.obj
    return (f"'{type_name}' is not an array type, but the value is "
            f"{format_shape(array_shape(arr))} elements; an array type "
            f"says its shape, as '{type_name}[]' or "
            f"'{type_name}[{arr.sizeof}]'")


def _array_type_name(elem_type: str, dims: list[int | None]) -> str:
    """Write the type of an array of `elem_type` with these dimensions.

    With no dimensions left there is no array, so the element type
    stands alone.  This is the inverse of _parse_array_type.
    """
    if not dims:
        return elem_type
    return elem_type + "[" + ",".join(
        "" if d is None else str(d) for d in dims) + "]"


def array_shape(arr: "ArrayValue") -> list[int | None]:
    """Return the dimensions of a nested array.

    A matrix reports [rows, columns], a plain array [length].  A level
    whose rows have different lengths has no single width to report, so
    it reports None and the walk stops there: the rank is still known
    even where an extent is not.
    """
    dims: list[int | None] = [arr.sizeof]
    rows = arr.values()
    while rows:
        inner = []
        for row in rows:
            if isinstance(row, SomeValue):
                row = row.value
            if not isinstance(row, ObjectValue) or not isinstance(row.obj, ArrayValue):
                return dims
            inner.append(row.obj)
        widths = {row.sizeof for row in inner}
        if len(widths) != 1:
            dims.append(None)
            return dims
        dims.append(widths.pop())
        rows = [elem for row in inner for elem in row.values()]
    return dims


def format_shape(dims: list[int | None]) -> str:
    """Render dimensions the way an array type writes them."""
    return "\N{MULTIPLICATION SIGN}".join(
        "?" if d is None else str(d) for d in dims)


def declared_rank(type_name: str | None) -> int:
    """How many containers deep the type says a value written with it is.

    `i64` is 0, `i64[]` is 1, `i64[2,3]` is 2.  This is one half of
    what decides threading: a parameter asking for this many and handed
    more is handed a container of what it asked for.

    Not `_parse_array_type`, whose element-type pattern is a word or a
    parenthesized run: a generic array `T'[]` matches neither, and
    reading it as no array at all would quietly make every generic
    array parameter unthreadable.
    """
    if type_name is None:
        return 0
    name = resolve_type_alias(type_name)
    base, _ = _split_optional_type(name)
    base = base.strip()
    rank = 0
    while True:
        # A tuple is one value written with brackets of its own, so the
        # walk stops at it rather than counting its commas.
        if parse_tuple_type(base) is not None:
            return rank
        m = re.search(r"\[(\d*(?:,\d*)*)\]$", base)
        if m is None:
            return rank
        rank += len(m.group(1).split(","))
        base = base[:m.start()]


def value_rank(value: "Value") -> int:
    """How many containers deep a value is.

    Measured down the first element of each level rather than across
    every element: a walk of the whole value would cost what the
    operation itself costs, and a ragged value would answer with the
    depth its shallowest branch reaches rather than the depth it has.
    An element that does not match what that says is met by the
    parameter it is handed to, which names it.
    """
    v = value.value if isinstance(value, SomeValue) else value
    if not isinstance(v, ObjectValue) or not isinstance(v.obj, ArrayValue):
        return 0
    if v.obj.sizeof == 0:
        return 1
    return 1 + value_rank(v.obj.get(0))


def threaded_array(results: list["Value"],
                   fallback_type: str | None = None) -> "ObjectValue":
    """Collect one level of a threaded call into an array.

    The structure is what was taken apart; the element type is what
    came back.  Comparing numbers answers with truth values, and an
    array that says it holds numbers refuses to hold those -- which is
    what an element type copied from the operands would say.

    A length is not carried over: what a computed value is bound to
    says whether it is fixed, and coerce_to_type settles that where it
    is bound.
    """
    kinds = {runtime_type_of(r) for r in results}
    element_type = (kinds.pop() if len(kinds) == 1
                    else None if kinds else fallback_type)
    return ObjectValue(ArrayValue(results, element_type=element_type))


# The arbitrary-precision types.  A value of one has no fixed width, so
# holding it needs a representation the bootstrap does not carry; they
# belong to the full language.  See spec/spec.md, "Two Languages, One
# Specification".
_FULL_LANGUAGE_TYPES: dict[str, str] = {"int": "i64", "float": "f64"}


def check_bootstrap_type(type_name: str, where: str):
    """Refuse a type the bootstrap implementation does not provide.

    A declared type is what asks for a representation; an untyped
    literal does not, and is arbitrary-precision while it is being
    computed with, so it is left alone.
    """
    # The written name, not what it resolves to.  A generic that infers
    # int was not a declaration of one, and an alias that names int is
    # refused where the alias is declared.
    elements = parse_tuple_type(type_name)
    if elements is not None:
        for element in elements:
            check_bootstrap_type(element, where)
        return
    base, _ = _split_optional_type(type_name)
    arr = _parse_array_type(base)
    if arr is not None:
        base = arr[0]
    sized = _FULL_LANGUAGE_TYPES.get(base)
    if sized is None:
        return
    raise coded(2272, TypeError(
        f"{where}: '{base}' is an arbitrary-precision type, which the "
        f"bootstrap implementation does not provide; use a sized type "
        f"such as {sized}"))


@_functools.lru_cache(maxsize=None)
def parse_tuple_type(type_name: str) -> list[str] | None:
    """The element types a tuple type names, or None for any other type.

    Written as the values are -- `(i64, str)` for `(1i64, "two")` --
    and read the same way, so an element may itself be a tuple, an
    array, or an optional.
    """
    if not type_name or not type_name.startswith("(") or not type_name.endswith(")"):
        return None
    elements: list[str] = []
    depth = 0
    current = ""
    for ch in type_name[1:-1]:
        if ch == "," and depth == 0:
            elements.append(current.strip())
            current = ""
            continue
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
            if depth < 0:
                return None
        current += ch
    elements.append(current.strip())
    if len(elements) < 2 or any(not e for e in elements):
        return None
    return elements


def validate_type(type_name: str) -> bool:
    got = _type_memo.get(type_name)
    if got is not None:
        return got
    ok = _validate_type_uncached(type_name)
    _type_memo[type_name] = ok
    return ok


def _validate_type_uncached(type_name: str) -> bool:
    """Return True if type_name is a known builtin type (with optional/expected/array modifiers)."""
    type_name = resolve_type_alias(type_name)
    if is_generic_type(type_name):
        return True
    tuple_elements = parse_tuple_type(type_name)
    if tuple_elements is not None:
        return all(validate_type(e) for e in tuple_elements)
    base, opt_err = _split_optional_type(type_name)
    arr = _parse_array_type(base)
    if arr is not None:
        base = arr[0]
    base = resolve_type_alias(base)
    elements = parse_tuple_type(base)
    if elements is not None:
        return all(validate_type(e) for e in elements)
    if parse_container_type(base) is not None:
        kind, args = parse_container_type(base)
        return all(validate_type(a) for a in args)
    if base in BUILTIN_TYPES or base in _USER_TYPES:
        return True
    # An integer type may state its width instead of carrying a name.
    return _parse_int_width(base) is not None


def validate_param_type(param_type: str, func_name: str, param_name: str):
    """Validate that a parameter type annotation is a known builtin type."""
    if not validate_type(param_type):
        raise TypeError(
            f"in {func_name}: parameter '{param_name}' has unknown type '{param_type}'")
    check_bootstrap_type(param_type,
                         f"in {func_name}: parameter '{param_name}'")


def coerce_arg(value: "Value", param_type: str, func_name: str,
               param_name: str, unit=None) -> "Value":
    """Coerce a runtime argument to match a declared parameter type.

    A parameter that states a unit has it applied before this runs, so
    a value still carrying one here is meeting a parameter that states
    none, and parting with it has to be said.
    """
    if unit is None:
        tv = type(value)
        if tv is IntValue:
            if value.width == param_type:
                return value
            if value.width == "int" and _parse_int_width(param_type) is not None:
                # an untyped literal adopts a stated width directly,
                # range-checked the same way the long path checks it
                return IntValue(check_int(value.value, param_type),
                                param_type)
        elif tv is StrValue:
            if param_type == "str":
                return value
        elif tv is BoolValue:
            if param_type == "bool":
                return value
        elif tv is CharValue:
            if param_type == "char":
                return value
        elif tv is ObjectValue:
            o = value.obj
            to = type(o)
            if to is StructInstance:
                # a struct argument meeting its own struct's name
                if o.struct_type.name == param_type:
                    return value
            elif to is ArrayValue:
                # an array already measured as T[] meeting T[]
                et = o.element_type
                if et is not None and o.fixed_size is None \
                        and o.element_unit is None \
                        and len(param_type) == len(et) + 2 \
                        and param_type.startswith(et) \
                        and param_type.endswith("[]"):
                    return value
    param_type = resolve_type_alias(param_type)
    if is_generic_type(param_type) and _parse_array_type(param_type) is None \
            and parse_tuple_type(param_type) is None:
        # A parameter that is nothing but a generic takes the value as
        # it is, unit and all: what it says about the argument is that
        # every position naming the same generic sees the same type,
        # which is settled before this.
        return value
    refuse_partial_application(value, param_type)
    if unit is not None:
        # The parameter states the unit, so what arrives measured is
        # what it asked for; the type describes what holds the number.
        return coerce_to_type(value, param_type, unit)
    if isinstance(value, UnitValue):
        raise coded(2326, TypeError(
            f"{func_name}: parameter '{param_name}' is {param_type}, which "
            f"carries no unit, but the argument is "
            f"{value.unit.display_name}; use @dropunit to part with it"))
    base, opt_err = _split_optional_type(param_type)
    if opt_err is not None and opt_err == "":
        if isinstance(value, NoneValue):
            return value
        if isinstance(value, SomeValue):
            return SomeValue(coerce_arg(value.value, base, func_name, param_name))
        if isinstance(value, ExpectedValue):
            return value
        return SomeValue(coerce_arg(value, base, func_name, param_name))
    if opt_err is not None and opt_err != "":
        if isinstance(value, ExpectedValue):
            return value
        if isinstance(value, NoneValue):
            return value
        return ExpectedValue.ok(coerce_arg(value, base, func_name, param_name))

    if parse_tuple_type(param_type) is not None:
        # A tuple type says what each element is, and coerce_to_type
        # measures the value against it element by element.
        try:
            return coerce_to_type(value, param_type)
        except TypeError as e:
            raise coded(2764, TypeError(
                f"{func_name}: argument '{param_name}': {e}")) from None

    if param_type == "fn":
        if not isinstance(value, (FuncValue, LambdaValue, BuiltinFunc,
                                  BuiltinBoundMethod)):
            raise TypeError(
                f"{func_name}: argument '{param_name}' expected a function, "
                f"got {runtime_type_of(value)}")
        return value

    if param_type == "syntax":
        if not isinstance(value, SyntaxValue):
            raise TypeError(
                f"{func_name}: argument '{param_name}' expected a piece of "
                f"the program, got {runtime_type_of(value)}")
        return value

    if param_type == "bool":
        if not isinstance(value, BoolValue):
            raise TypeError(
                f"{func_name}: argument '{param_name}' expected bool, "
                f"got {type(value).__name__}")
        return value

    if param_type == "str":
        if not isinstance(value, StrValue):
            raise TypeError(
                f"{func_name}: argument '{param_name}' expected str, "
                f"got {type(value).__name__}")
        return value

    if param_type == "char":
        if not isinstance(value, CharValue):
            raise coded(2014, TypeError(
                f"{func_name}: argument '{param_name}' expected char, "
                f"got {runtime_type_of(value)}"))
        return value

    if param_type == "\N{EMPTY SET}":
        if not isinstance(value, NoneValue):
            raise TypeError(
                f"{func_name}: argument '{param_name}' expected \N{EMPTY SET}, "
                f"got {type(value).__name__}")
        return value

    # A parameter states a type the way a binding does, so an array
    # meeting one that names no array is refused the same way.
    unwrapped_arg = value.value if isinstance(value, SomeValue) else value
    mismatch = array_type_mismatch(unwrapped_arg, param_type)
    if mismatch is not None:
        raise coded(2765, TypeError(
            f"{func_name}: argument '{param_name}': {mismatch}"))

    arr_info = _parse_array_type(param_type)
    if arr_info is not None:
        elem_type, declared = arr_info
        unwrapped = value
        if isinstance(value, SomeValue):
            unwrapped = value.value
        if isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
            actual = array_shape(unwrapped.obj)
            # The type names one entry per dimension, so an argument
            # with a different number of them does not fit however long
            # its outermost one happens to be.  Slicing a matrix along
            # one dimension keeps the others, which is what a row range
            # meets here.
            if len(actual) != len(declared):
                got = (f"array of length {actual[0]}" if len(actual) == 1
                       else f"a {format_shape(actual)} array")
                raise coded(2766, TypeError(
                    f"{func_name}: argument '{param_name}' expected "
                    f"{param_type} "
                    f"({len(declared)} dimension"
                    f"{'' if len(declared) == 1 else 's'}), "
                    f"got {got}"))
            for axis, (want, have) in enumerate(zip(declared, actual)):
                if have is None:
                    # An open dimension is one extent the type does not
                    # name, not the absence of one, so rows of differing
                    # lengths are not a dimension at all.
                    raise coded(2767, TypeError(
                        f"{func_name}: argument '{param_name}' expected "
                        f"{param_type} (dimension {axis + 1} is one extent), "
                        f"got a {format_shape(actual)} array whose rows "
                        f"differ in length"))
                if want is None or want == have:
                    continue
                if len(declared) == 1:
                    raise coded(2768, TypeError(
                        f"{func_name}: argument '{param_name}' expected "
                        f"{param_type} (length {want}), "
                        f"got array of length {have}"))
                raise coded(2769, TypeError(
                    f"{func_name}: argument '{param_name}' expected "
                    f"{param_type} (dimension {axis + 1} is {want}), "
                    f"got a {format_shape(actual)} array"))
            # The shape is right; what it holds still has to be.  A
            # parameter states an element type the way a binding does,
            # and until now only the shape was ever measured -- so a
            # str[] met an i32[] parameter and the body read strings
            # out of what it had been told were numbers.
            try:
                return coerce_to_type(unwrapped, param_type)
            except (TypeError, OverflowError) as e:
                raise coded(2770, TypeError(
                    f"{func_name}: argument '{param_name}': "
                    f"{e}")) from None
        if isinstance(unwrapped, ObjectValue) and hasattr(unwrapped.obj, "data"):
            raw = bytes(unwrapped.obj.data)
            elements = [mk_int(b, elem_type) for b in raw]
            return ObjectValue(ArrayValue(elements, element_type=elem_type))
        raise TypeError(
            f"{func_name}: argument '{param_name}' expected {param_type}, "
            f"got {type(value).__name__}")

    if param_type in _TYPE_BITS or param_type == "int":
        if isinstance(value, FloatValue):
            raise TypeError(
                f"{func_name}: argument '{param_name}' expected {param_type}, "
                f"got {type(value).__name__}")
        if not isinstance(value, IntValue):
            raise coded(2015, TypeError(
                f"{func_name}: argument '{param_name}' expected {param_type}, "
                f"got {type(value).__name__}"))
        return coerce_to_type(value, param_type)

    if param_type in FLOAT_TYPES:
        if isinstance(value, IntValue):
            if not _int_is_exact_in_float(value.value, param_type):
                raise coded(2273, TypeError(
                    f"{func_name}: argument '{param_name}' is {value.value}, "
                    f"which needs more significant bits than {param_type} "
                    f"has ({_SIGNIFICAND_BITS[param_type]})"))
            return mk_float(float(value.value), param_type)
        if isinstance(value, FloatValue):
            try:
                checked = check_float(value.value, param_type)
            except OverflowError as e:
                raise TypeError(
                    f"{func_name}: argument '{param_name}': {e}") from None
            return mk_float(checked, param_type)
        raise TypeError(
            f"{func_name}: argument '{param_name}' expected {param_type}, "
            f"got {type(value).__name__}")

    if is_generic_type(param_type):
        return value

    if param_type in _STRUCT_TYPES:
        if not struct_type_admits(param_type, value):
            raise coded(2016, TypeError(
                f"{func_name}: argument '{param_name}' expected "
                f"{param_type}, got {runtime_type_of(value)}"))
        return value

    if param_type in _ENUM_TYPES:
        if isinstance(value, IntValue) and not isinstance(value, UnitValue):
            # exhaustiveness speaks for itself; the argument's name is
            # still worth adding
            try:
                return enum_admit(param_type, value)
            except TypeError as e:
                raise coded(2830, TypeError(
                    f"{func_name}: argument '{param_name}': {e}")) from None
        if not (isinstance(value, EnumValue)
                and value.enum_type.name == param_type):
            raise coded(2017, TypeError(
                f"{func_name}: argument '{param_name}' expected "
                f"{param_type}, got {runtime_type_of(value)}"))
        return value

    if param_type in _SUM_TYPES:
        try:
            return sum_type_settle(param_type, value)
        except TypeError as e:
            raise coded(2274, TypeError(
                f"{func_name}: argument '{param_name}': {e}")) from None

    if param_type in _USER_TYPES:
        return value

    raise TypeError(
        f"{func_name}: argument '{param_name}' has unknown type '{param_type}'")


_SCALAR_TARGETS = {"str", "bool", "int", "char"}


def _scalar_kind_mismatch(value: "Value", target: str) -> str | None:
    """Say how a scalar value differs in kind from the type named.

    Widths convert within a kind and an integer becomes a float, but
    the kinds themselves do not run together: a string is not a number
    and a number is not a string.  Returns a description, or None where
    there is nothing to object to.
    """
    if target not in _SCALAR_TARGETS and target not in _TYPE_BITS \
            and target not in FLOAT_TYPES:
        return None
    if isinstance(value, StrValue):
        return None if target == "str" else "a string"
    # A character is what a string is made of rather than a number or a
    # string of one, so it converts to neither, and a number becomes
    # one only where the program says .chr().
    if isinstance(value, CharValue):
        return None if target == "char" else "a character"
    if target == "char":
        kind = {BoolValue: "a boolean", IntValue: "an integer",
                FloatValue: "a number", StrValue: "a string"}.get(type(value))
        if kind is None:
            return None
        return (f"{kind}; a number becomes a character with .chr()"
                if kind in ("an integer", "a number") else kind)
    if target == "str":
        kind = {BoolValue: "a boolean", IntValue: "an integer",
                FloatValue: "a number"}.get(type(value))
        return kind
    if isinstance(value, BoolValue):
        return None if target == "bool" else "a boolean"
    if target == "bool":
        return "a number" if isinstance(value, (IntValue, FloatValue)) else None
    if isinstance(value, FloatValue) and target not in FLOAT_TYPES:
        return "a floating-point number"
    return None


def convert_unit_value(value: "UnitValue", target_unit, mk=None) -> "UnitValue":
    """Carry a measured value to another scale of what it measures.

    `mk` builds the integer, so a caller that wraps on overflow keeps
    wrapping and one that reports keeps reporting.
    """
    from fractions import Fraction
    if mk is None:
        mk = mk_int
    if not value.unit.same_dimension(target_unit):
        if value.unit.stands_in_for(target_unit):
            # A measure that stands in for another is relabelled, not
            # rescaled: `unit tok -> ptrdiff` says a token index may be
            # used as a ptrdiff, not that one token is so many of them.
            return UnitValue(value.inner, target_unit)
        raise coded(2327, TypeError(
            f"incompatible units: {value.unit.display_name} "
            f"and {target_unit.display_name}"))
    ratio = value.unit.factor / target_unit.factor
    inner = value.inner
    if isinstance(inner, IntValue):
        result = Fraction(inner.value) * ratio
        if result.denominator != 1:
            raise TypeError(
                f"cannot convert {inner.value} {value.unit.display_name} to "
                f"{target_unit.display_name} without loss "
                f"(result is {float(result)})")
        return UnitValue(mk(int(result), inner.width), target_unit)
    if isinstance(inner, FloatValue):
        return UnitValue(
            mk_float(float(Fraction(inner.value) * ratio), inner.width),
            target_unit)
    raise TypeError(f"cannot convert {type(inner).__name__} with units")


def apply_unit(value: Value, unit, mk=None) -> Value:
    """Give a value the unit a definition states for it.

    A unit measures a number, and a container is not one: what a
    declaration of an array measures is each of the things in it,
    however deep they sit.  So this reaches through an array rather
    than wrapping it, which is what keeps a measured array indexable --
    a unit wrapped around the container is a value nothing can read an
    element out of.
    """
    if unit is None:
        return value
    if isinstance(value, SomeValue):
        return SomeValue(apply_unit(value.value, unit, mk))
    if isinstance(value, ObjectValue) and isinstance(value.obj, ArrayValue):
        arr = value.obj
        return ObjectValue(ArrayValue(
            [apply_unit(arr.get(i), unit, mk) for i in range(arr.sizeof)],
            element_type=arr.element_type, element_unit=unit,
            fixed_size=arr.fixed_size))
    if isinstance(value, UnitValue):
        return convert_unit_value(value, unit, mk)
    return UnitValue(value, unit)


def _coerce_container(value: Value, target_width: str, container) -> Value:
    """Measure a dictionary or a set against the type that says what it holds.

    An empty one takes the type and holds nothing of it, which is what
    lets ⸨⸩ be written at all: it says neither what it holds nor which
    of the two it is, and the type says both.
    """
    kind, args = container
    inner = value.value if isinstance(value, SomeValue) else value
    want = HashValue if kind == "std.dict" else SetValue
    other = "a set" if kind == "std.dict" else "a dictionary"
    if isinstance(inner, ObjectValue) and isinstance(inner.obj, (HashValue,
                                                                 SetValue)):
        held = inner.obj
        if not isinstance(held, want):
            if held.sizeof == 0:
                held = want()
            else:
                raise TypeError(
                    f"'{target_width}' is {'a dictionary' if want is HashValue else 'a set'}, "
                    f"but the value is {other}")
        if kind == "std.dict":
            built = HashValue(key_type=args[0], value_type=args[1])
            for key, held_value in held.pairs():
                built.put(coerce_to_type(key, args[0]),
                          coerce_to_type(held_value, args[1]))
        else:
            built = SetValue(value_type=args[0])
            for held_value in held.values():
                built.put(coerce_to_type(held_value, args[0]))
        return ObjectValue(built)
    raise TypeError(
        f"'{target_width}' is {'a dictionary' if want is HashValue else 'a set'}, "
        f"but the value is {runtime_type_of(inner)}")


def coerce_to_type(value: Value, target_width: str, unit=None, mk=None) -> Value:
    """Measure a value against a type, and against a unit where one is stated.

    The unit is settled *before* the width: a value already measuring
    something has to be carried to what is asked for, and carrying it
    is what refuses a length where a duration was wanted.  Settling the
    width first would strip the unit and then label the bare number
    with the one asked for, which turns a mistake into a conversion
    nobody wrote.
    """
    if unit is None:
        return _coerce_to_type(value, target_width, None)
    if isinstance(value, SomeValue):
        return SomeValue(coerce_to_type(value.value, target_width, unit, mk))
    inner = value
    if isinstance(inner, ObjectValue) and isinstance(inner.obj, ArrayValue):
        # An array is taken apart by the branch below, which carries the
        # unit down to each element and records it on the way.
        return _coerce_to_type(value, target_width, unit)
    measured = apply_unit(value, unit, mk)
    if not isinstance(measured, UnitValue):
        return _coerce_to_type(measured, target_width, unit)
    return UnitValue(_coerce_to_type(measured.inner, target_width, None),
                     measured.unit)


def refuse_partial_application(value: Value, target: str):
    """An unfinished call meeting a type that is no function.

    A call with too few arguments curries, which is right where the
    result goes on to be called; where it meets a declared type instead
    -- and no type annotation names a function -- the mistake is the
    call's arity, so the error says which call and how short it was,
    rather than surfacing far away as a lambda where a number was
    wanted.
    """
    if (isinstance(value, LambdaValue) and value.partial_func is not None
            and not is_generic_type(target)):
        func = value.partial_func
        raise coded(2275, TypeError(
            f"'{func.name}' was called with {len(value.partial_args)} of "
            f"its {len(func.params)} arguments; a call this unfinished "
            f"answers a function, not {target}"))


def _coerce_to_type(value: Value, target_width: str, unit=None) -> Value:
    """Coerce a value to a target integer type.

    For scalar IntValue, checks that the value fits the target type.
    For ObjectValue(ArrayValue), coerces each element and sets element_type.
    Returns the value unchanged if no coercion is needed.
    Raises OverflowError if the value does not fit.
    """
    # Already exactly the type asked for.  An integer of that width has
    # nothing left to settle, and every question below is about a value
    # that is not it -- a container, a tuple, an optional, a unit, a
    # kind that does not match.  This is most coercions, an i64 handed
    # where an i64 was wanted, so it is asked before any of them.
    if type(value) is IntValue and value.width == target_width \
            and target_width != "int":
        return value
    target_width = resolve_type_alias(target_width)
    refuse_partial_application(value, target_width)
    arr_ty = _parse_array_type(target_width)
    if arr_ty is not None and arr_ty[0] in FAST_TYPES:
        raise TypeError(
            f"fast type '{arr_ty[0]}' cannot be used as array element type")
    if target_width is None or target_width == "int":
        # `int` holds anything an untyped literal could be, so the
        # value settles on it rather than staying uncommitted.
        return settle_untyped(value)
    if not validate_type(target_width):
        raise coded(2112, TypeError(f"unknown type '{target_width}'"))

    container = parse_container_type(target_width)
    if container is not None:
        return _coerce_container(value, target_width, container)

    elements = parse_tuple_type(target_width)
    if elements is not None:
        # A tuple type says what each element is, one by one: there is
        # no width for the whole of it to settle on, only the elements'
        # own.
        inner = value.value if isinstance(value, SomeValue) else value
        if not isinstance(inner, TupleValue):
            raise coded(2771, TypeError(
                f"'{target_width}' is a tuple type, but the value is "
                f"{runtime_type_of(inner)}"))
        if len(inner.elements) != len(elements):
            raise coded(2276, TypeError(
                f"'{target_width}' has {len(elements)} elements, but the "
                f"value has {len(inner.elements)}"))
        return TupleValue([coerce_to_type(v, t)
                           for v, t in zip(inner.elements, elements)])

    # An optional or expected target says what a value has to be when
    # there is one; absence is what the ? or ! admits on its own.
    base, opt_err = _split_optional_type(target_width)
    if opt_err is not None:
        if isinstance(value, (NoneValue, ExpectedValue)):
            return value
        if isinstance(value, SomeValue):
            return SomeValue(coerce_to_type(value.value, base))
        settled = coerce_to_type(value, base)
        return (SomeValue(settled) if opt_err == ""
                else ExpectedValue.ok(settled))
    # A scalar of one kind is not a value of another, whatever the
    # widths involved.
    mismatch = _scalar_kind_mismatch(value, target_width)
    if mismatch is not None:
        raise coded(2772, TypeError(
            f"'{target_width}' cannot hold {mismatch}"))

    # A type states no unit, so a value carrying one is not that type.
    # Parting with a unit is a real change and is said with @dropunit
    # rather than done quietly at a binding.
    if unit is None and isinstance(value, UnitValue):
        raise TypeError(
            f"'{target_width}' carries no unit, but the value is "
            f"{value.unit.display_name}; use @dropunit to part with it")

    # An array is coerced element by element further down, so a named
    # type here describes the elements rather than the array.
    scalar = not (isinstance(value, ObjectValue)
                  and isinstance(value.obj, ArrayValue))

    if scalar and target_width in _STRUCT_TYPES:
        if not struct_type_admits(target_width, value):
            raise coded(2831, TypeError(
                f"'{target_width}' is a struct, "
                f"but the value is {runtime_type_of(value)}"))
        return value

    if scalar and target_width in _ENUM_TYPES:
        return enum_admit(target_width, value)

    if scalar and target_width in _SUM_TYPES:
        # A sum type admits its alternatives and nothing else.  The
        # value keeps its own type, which is what says which
        # alternative it is.
        return sum_type_settle(target_width, value)
    if isinstance(value, UnitValue):
        value = value.inner
    if target_width in FLOAT_TYPES:
        # A float carries its width like an integer does, so a target
        # that names one decides it.
        if isinstance(value, IntValue):
            if not _int_is_exact_in_float(value.value, target_width):
                raise coded(2277, TypeError(
                    f"{value.value} needs more significant bits than "
                    f"{target_width} has ({_SIGNIFICAND_BITS[target_width]}), "
                    f"so it would not survive the conversion"))
            return mk_float(float(value.value), target_width)
        if isinstance(value, FloatValue):
            return mk_float(check_float(value.value, target_width),
                            target_width)
    if isinstance(value, IntValue):
        # A value that does not fit the type it is being given is the
        # same mistake whichever side of the range it falls, and the
        # same mistake arithmetic reports.  Wrapping it here would mean
        # `let y : u8 = 256` and `y + 1` on a u8 of 255 answering
        # differently about the same number and the same type.
        if value.width == target_width:
            # Already that type: the same object serves, which is what
            # lets a container of them pass by identity below.
            return value
        check_int(value.value, target_width)
        return IntValue(value.value, target_width)
    if isinstance(value, ObjectValue) and isinstance(value.obj, ArrayValue):
        arr = value.obj
        arr_info = _parse_array_type(target_width)
        if arr_info is None:
            raise coded(2773, TypeError(array_type_mismatch(value, target_width)))
        # T[] says dynamic and T[n] says fixed; either way the target
        # decides, not the source.
        elem_type, dims = arr_info
        declared = dims[0]
        if declared is not None and arr.sizeof != declared:
            raise coded(2774, TypeError(
                f"array size mismatch: type '{target_width}' declares "
                f"{declared} elements, got {arr.sizeof}"))
        # A dimension the target still has describes the rows, so what
        # each element is measured against is the type with that one
        # dimension taken off.
        elem_target = _array_type_name(elem_type, dims[1:])
        # An array already measured against this element type passes by
        # identity: re-measuring it element by element would cost the
        # array's length at every call that hands it over, which is
        # what made compiling the compiler quadratic.
        if (arr.element_type == elem_target
                and arr.element_unit == unit
                and arr.fixed_size == declared):
            return value
        coerced = []
        untouched = True
        for i in range(arr.sizeof):
            before = arr.get(i)
            after = coerce_to_type(before, elem_target, unit)
            if after is not before:
                untouched = False
            coerced.append(after)
        if (untouched and arr.fixed_size == declared):
            # Every element passed as itself, so the array is already
            # of this type; it is stamped so the next pass is free.
            arr.element_type = elem_target
            arr.element_unit = unit
            return value
        return ObjectValue(ArrayValue(coerced, element_type=elem_target,
                                      element_unit=unit,
                                      fixed_size=declared))
    return value
