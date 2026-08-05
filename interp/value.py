"""Runtime value types for the newlang language.

Each runtime value is wrapped in one of these classes. The evaluator
operates on these values rather than raw Python objects to support
type checking and proper error messages.
"""


BUILTIN_TYPES: set[str] = {
    "i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64",
    "usize", "int", "bool", "none", "byte",
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
        return "none"

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


class FuncValue(Value):
    """A user-defined function (closure over an environment)."""

    __slots__ = ("name", "params", "body", "env", "ret_type")

    def __init__(self, name, params, body, env, ret_type=None):
        self.name = name
        self.params = params      # list of (param_name, param_type)
        self.body = body          # list of statement AST nodes
        self.env = env            # environment snapshot at definition time
        self.ret_type = ret_type


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


class ArrayValue(Value):
    """A mutable array of runtime Values with dynamic growth.

    Elements can be read via get() and written via set().
    Setting an index beyond the current length zero-fills the gap.
    If element_type is set, stored values are automatically coerced.
    """

    __slots__ = ("elements", "element_type")

    def __init__(self, elements=None, element_type: str | None = None):
        self.elements = list(elements) if elements else []
        self.element_type = element_type

    def get(self, index: int) -> Value:
        """Return element at index; returns IntValue(0) if out of range."""
        if 0 <= index < len(self.elements):
            return self.elements[index]
        return mk_int(0, self.element_type or "untyped")

    @property
    def sizeof(self) -> int:
        return len(self.elements)

    def set(self, index: int, value: Value):
        """Set element at index, coercing to element_type if set."""
        if self.element_type is not None and isinstance(value, IntValue):
            value = mk_int(value.value, self.element_type)
        while len(self.elements) <= index:
            self.elements.append(mk_int(0, self.element_type or "untyped"))
        self.elements[index] = value


def mk_int(value: int, width: str = "int") -> IntValue:
    """Create an IntValue, wrapping to the type's range if typed."""
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


def validate_param_type(param_type: str, func_name: str, param_name: str):
    """Validate that a parameter type annotation is a known builtin type."""
    base = param_type.lstrip("?")
    if base.endswith("[]"):
        base = base[:-2]
    if base not in BUILTIN_TYPES:
        raise TypeError(
            f"in {func_name}: parameter '{param_name}' has unknown type '{param_type}'")


def coerce_arg(value: "Value", param_type: str, func_name: str, param_name: str) -> "Value":
    """Coerce a runtime argument to match a declared parameter type."""
    if param_type.startswith("?"):
        inner = param_type[1:]
        if isinstance(value, NoneValue):
            return value
        if isinstance(value, SomeValue):
            return SomeValue(coerce_arg(value.value, inner, func_name, param_name))
        return SomeValue(coerce_arg(value, inner, func_name, param_name))

    if param_type == "bool":
        if not isinstance(value, BoolValue):
            raise TypeError(
                f"{func_name}: argument '{param_name}' expected bool, "
                f"got {type(value).__name__}")
        return value

    if param_type == "none":
        if not isinstance(value, NoneValue):
            raise TypeError(
                f"{func_name}: argument '{param_name}' expected none, "
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

    For scalar IntValue, wraps to the target width.
    For ObjectValue(ArrayValue), coerces each element and sets element_type.
    Returns the value unchanged if no coercion is needed.
    """
    if target_width is None or target_width == "int":
        return value
    if isinstance(value, IntValue):
        return mk_int(value.value, target_width)
    if isinstance(value, ObjectValue) and isinstance(value.obj, ArrayValue):
        coerced = [coerce_to_type(e, target_width) for e in value.obj.elements]
        return ObjectValue(ArrayValue(coerced, element_type=target_width))
    return value
