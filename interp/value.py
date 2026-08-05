"""Runtime value types for the newlang language.

Each runtime value is wrapped in one of these classes. The evaluator
operates on these values rather than raw Python objects to support
type checking and proper error messages.
"""


BUILTIN_TYPES: set[str] = {
    "i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64",
    "usize", "int", "bool", "∅", "byte",
    "i8fast", "u8fast", "i16fast", "u16fast",
    "i32fast", "u32fast", "i64fast", "u64fast",
}

# Platform-specific fast type mapping (x86_64: sub-32 → 32, 32/64 → 64).
_FAST_TYPE_UNDERLYING: dict[str, str] = {
    "u8fast": "u32", "i8fast": "i32",
    "u16fast": "u32", "i16fast": "i32",
    "u32fast": "u64", "i32fast": "i64",
    "u64fast": "u64", "i64fast": "i64",
}

FAST_TYPES: frozenset[str] = frozenset(_FAST_TYPE_UNDERLYING)

_TYPE_BITS: dict[str, int] = {
    "u8": 8, "i8": 8, "byte": 8,
    "u16": 16, "i16": 16,
    "u32": 32, "i32": 32,
    "u64": 64, "i64": 64,
    "usize": 64,
    "u8fast": 32, "i8fast": 32,
    "u16fast": 32, "i16fast": 32,
    "u32fast": 64, "i32fast": 64,
    "u64fast": 64, "i64fast": 64,
}

_TYPE_MASK: dict[str, int] = {
    "u8": 0xFF, "i8": 0xFF, "byte": 0xFF,
    "u16": 0xFFFF, "i16": 0xFFFF,
    "u32": 0xFFFFFFFF, "i32": 0xFFFFFFFF,
    "u64": 0xFFFFFFFFFFFFFFFF, "i64": 0xFFFFFFFFFFFFFFFF,
    "usize": 0xFFFFFFFFFFFFFFFF,
    "u8fast": 0xFFFFFFFF, "i8fast": 0xFFFFFFFF,
    "u16fast": 0xFFFFFFFF, "i16fast": 0xFFFFFFFF,
    "u32fast": 0xFFFFFFFFFFFFFFFF, "i32fast": 0xFFFFFFFFFFFFFFFF,
    "u64fast": 0xFFFFFFFFFFFFFFFF, "i64fast": 0xFFFFFFFFFFFFFFFF,
}


def resolve_width(w1: str, w2: str) -> str:
    """Determine the result type when combining two integer types.

    Rules (wider wins):
    - same + same → same
    - int + fixed → int (arbitrary precision is wider than any fixed type)
    - fixed + fixed (different) → wider fixed type
    """
    if w1 == w2:
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
        raise OverflowError(
            f"integer overflow: {value} does not fit in {width} "
            f"(range {lo}..{hi})")
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


class StrValue(Value):
    """String value (UTF-8)."""

    __slots__ = ("value",)

    def __init__(self, value: str):
        self.value = value

    def display(self):
        return repr(self.value)

    def to_python(self):
        return self.value


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
        return f"some({self.value.display()})"

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

    __slots__ = ("name", "params", "body", "env", "ret_type", "is_replaceable")

    def __init__(self, name, params, body, env, ret_type=None,
                 is_replaceable: bool = False):
        self.name = name
        self.params = params
        self.body = body
        self.env = env
        self.ret_type = ret_type
        self.is_replaceable = is_replaceable


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

    __slots__ = ("name", "arity", "func")

    def __init__(self, name, arity, func):
        """
        Args:
            name: the function's name in the language namespace.
            arity: expected number of arguments (-1 for variadic).
            func: callable(values) -> Value where values is a list of Value args.
        """
        self.name = name
        self.arity = arity
        self.func = func

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
        return f"<{type(self.obj).__name__}>"


class BuiltinBoundMethod(Value):
    """A bound method on a Python object (exposed to newlang)."""

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
        self.underlying_type = underlying_type or "int"
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
                raise TypeError("range step must not be zero")
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


class ArrayValue(Value):
    """A mutable array of runtime Values with bounds checking.

    Elements can be read via get() and written via set().
    Both raise IndexError for out-of-bounds access.
    If element_type is set, stored values are automatically coerced.
    """

    __slots__ = ("elements", "element_type")

    def __init__(self, elements=None, element_type: str | None = None):
        self.elements = list(elements) if elements else []
        self.element_type = element_type

    def get(self, index: int) -> Value:
        """Return element at index; raises IndexError if out of range."""
        if 0 <= index < len(self.elements):
            return self.elements[index]
        raise IndexError(
            f"array index {index} out of range (length {len(self.elements)})")

    @property
    def sizeof(self) -> int:
        return len(self.elements)

    def set(self, index: int, value: Value):
        """Set element at index; raises IndexError if out of range."""
        if self.element_type is not None and isinstance(value, IntValue):
            value = mk_int(value.value, self.element_type)
        if index < 0 or index >= len(self.elements):
            raise IndexError(
                f"array index {index} out of range (length {len(self.elements)})")
        self.elements[index] = value


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


def _is_unsigned(width: str) -> bool:
    """Return True if width names an unsigned integer type."""
    return width.startswith("u") or width in ("byte", "usize")


def mk_int(value: int, width: str = "int") -> IntValue:
    """Create an IntValue with overflow semantics per type.

    Unsigned types wrap silently (modular arithmetic).
    Signed types and untyped 'int' raise OverflowError on overflow.
    """
    if _is_unsigned(width):
        return IntValue(wrap_int(value, width), width)
    return IntValue(check_int(value, width), width)


def mk_int_wrap(value: int, width: str = "int") -> IntValue:
    """Create an IntValue, wrapping to the type's range (for bitwise ops)."""
    return IntValue(wrap_int(value, width), width)


def mk_str(value):
    """Create a StrValue."""
    return StrValue(value)


def mk_bool(value):
    """Create a BoolValue."""
    return BoolValue(value)


def none():
    """Get the singleton NoneValue."""
    return NoneValue()


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


def _split_optional_type(type_name: str) -> tuple[str, str | None]:
    """Split a type string into base type and optional/expected error type.

    Returns (base, None) for plain types, (base, "") for T? optionals,
    (base, error_type) for T?E expected types.
    """
    qpos = type_name.find("?")
    if qpos < 0:
        return type_name, None
    return type_name[:qpos], type_name[qpos + 1:]


def validate_type(type_name: str) -> bool:
    """Return True if type_name is a known builtin type (with optional/expected/array modifiers)."""
    base, opt_err = _split_optional_type(type_name)
    if base.endswith("[]"):
        base = base[:-2]
    if not base in BUILTIN_TYPES:
        return False
    if opt_err is not None and opt_err != "":
        return True
    return True


def validate_param_type(param_type: str, func_name: str, param_name: str):
    """Validate that a parameter type annotation is a known builtin type."""
    if not validate_type(param_type):
        raise TypeError(
            f"in {func_name}: parameter '{param_name}' has unknown type '{param_type}'")


def coerce_arg(value: "Value", param_type: str, func_name: str, param_name: str) -> "Value":
    """Coerce a runtime argument to match a declared parameter type."""
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

    if param_type == "bool":
        if not isinstance(value, BoolValue):
            raise TypeError(
                f"{func_name}: argument '{param_name}' expected bool, "
                f"got {type(value).__name__}")
        return value

    if param_type == "\N{EMPTY SET}":
        if not isinstance(value, NoneValue):
            raise TypeError(
                f"{func_name}: argument '{param_name}' expected \N{EMPTY SET}, "
                f"got {type(value).__name__}")
        return value

    if param_type.endswith("[]"):
        elem_type = param_type[:-2]
        unwrapped = value
        if isinstance(value, SomeValue):
            unwrapped = value.value
        if isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
            return unwrapped
        if isinstance(unwrapped, ObjectValue) and hasattr(unwrapped.obj, "data"):
            raw = bytes(unwrapped.obj.data)
            elements = [mk_int(b, elem_type) for b in raw]
            return ObjectValue(ArrayValue(elements, element_type=elem_type))
        raise TypeError(
            f"{func_name}: argument '{param_name}' expected {param_type}, "
            f"got {type(value).__name__}")

    if param_type in _TYPE_BITS or param_type == "int":
        if not isinstance(value, IntValue):
            raise TypeError(
                f"{func_name}: argument '{param_name}' expected {param_type}, "
                f"got {type(value).__name__}")
        return coerce_to_type(value, param_type)

    raise TypeError(
        f"{func_name}: argument '{param_name}' has unknown type '{param_type}'")


def coerce_to_type(value: Value, target_width: str) -> Value:
    """Coerce a value to a target integer type.

    For scalar IntValue, checks that the value fits the target type.
    For ObjectValue(ArrayValue), coerces each element and sets element_type.
    Returns the value unchanged if no coercion is needed.
    Raises OverflowError if the value does not fit.
    """
    if target_width is None or target_width == "int":
        return value
    if not validate_type(target_width):
        raise TypeError(f"unknown type '{target_width}'")
    if isinstance(value, IntValue):
        if _is_unsigned(target_width):
            return IntValue(wrap_int(value.value, target_width), target_width)
        check_int(value.value, target_width)
        return IntValue(value.value, target_width)
    if isinstance(value, ObjectValue) and isinstance(value.obj, ArrayValue):
        coerced = [coerce_to_type(e, target_width) for e in value.obj.elements]
        return ObjectValue(ArrayValue(coerced, element_type=target_width))
    return value
