"""Runtime value types for the NGPL language.

Each runtime value is wrapped in one of these classes. The evaluator
operates on these values rather than raw Python objects to support
type checking and proper error messages.
"""


# The discard target.  Assigning to it evaluates the right-hand side and
# throws the result away; it names no storage, so it never needs to be
# declared and can never be read back.
DISCARD_NAME = "_"

BUILTIN_TYPES: set[str] = {
    "i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64",
    "usize", "int", "bool", "∅", "byte", "str",
    "i8fast", "u8fast", "i16fast", "u16fast",
    "i32fast", "u32fast", "i64fast", "u64fast",
    "f16", "f32", "f64", "bfloat", "float",
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


FLOAT_TYPES: frozenset[str] = frozenset({"f16", "f32", "f64", "bfloat", "float"})

_FLOAT_STRUCT_FMT: dict[str, str] = {
    "f16": "e",
    "f32": "f",
    "f64": "d",
    "bfloat": "e",
}


def _float_precision_bits(width: str) -> int:
    return {"f16": 16, "bfloat": 16, "f32": 32, "f64": 64, "float": 64}[width]


def resolve_float_width(w1: str, w2: str) -> str:
    if w1 == w2:
        return w1
    if w1 == "float" or w2 == "float":
        return "float"
    b1 = _float_precision_bits(w1)
    b2 = _float_precision_bits(w2)
    return w1 if b1 >= b2 else w2


def _clamp_float(value: float, width: str) -> float:
    import struct
    fmt = _FLOAT_STRUCT_FMT.get(width)
    if fmt is None:
        return float(value)
    if width == "bfloat":
        as_f32 = struct.pack("f", value)
        truncated = b"\x00\x00" + as_f32[2:]
        return struct.unpack("f", truncated)[0]
    return struct.unpack(fmt, struct.pack(fmt, value))[0]


class FloatValue(Value):
    """Floating-point value with a width annotation (f16, f32, f64, bfloat, float)."""

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

    __slots__ = ("name", "params", "body", "env", "ret_type", "is_replaceable",
                 "pack_param", "param_units", "is_impure", "param_refs",
                 "param_muts", "source_label")

    def __init__(self, name, params, body, env, ret_type=None,
                 is_replaceable: bool = False,
                 pack_param: tuple[str, str | None] | None = None,
                 param_units: dict[str, object] | None = None,
                 is_impure: bool = False,
                 param_refs: set[str] | None = None,
                 param_muts: set[str] | None = None):
        self.name = name
        self.params = params
        self.body = body
        self.env = env
        self.ret_type = ret_type
        self.is_replaceable = is_replaceable
        self.pack_param = pack_param
        self.param_units: dict[str, object] = param_units or {}
        self.is_impure = is_impure
        self.param_refs: set[str] = param_refs or set()
        self.param_muts: set[str] = param_muts or set()
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


class StructType(Value):
    """Runtime representation of a struct (product type) definition.

    repr_kind holds the layout attribute given by @repr(...), or None
    when the struct has no defined layout and the implementation is free
    to order and pad its fields as it sees fit.
    """

    __slots__ = ("name", "fields", "methods", "repr_kind", "_ref_self_methods")

    def __init__(self, name: str, fields: list[tuple[str, str]],
                 methods: dict[str, "FuncValue"] | None = None,
                 repr_kind: str | None = None):
        self.name = name
        self.fields = fields
        self.methods: dict[str, FuncValue] = methods or {}
        self.repr_kind = repr_kind
        self._ref_self_methods: set[str] = set()

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

    When _backing is set, the array is a view into a shared list
    at the given offset/length.  Reads and writes go through the backing.
    """

    __slots__ = ("elements", "element_type", "_backing", "_offset", "_length")

    def __init__(self, elements=None, element_type: str | None = None,
                 *, backing: list | None = None, offset: int = 0,
                 length: int | None = None):
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

    def get(self, index: int) -> Value:
        """Return element at index; raises IndexError if out of range."""
        n = self.sizeof
        if 0 <= index < n:
            if self._backing is not None:
                return self._backing[self._offset + index]
            return self.elements[index]
        raise IndexError(
            f"array index {index} out of range (length {n})")

    @property
    def sizeof(self) -> int:
        if self._backing is not None:
            return self._length
        return len(self.elements)

    def set(self, index: int, value: Value):
        """Set element at index; raises IndexError if out of range."""
        if self.element_type is not None and isinstance(value, IntValue):
            value = mk_int(value.value, self.element_type)
        n = self.sizeof
        if index < 0 or index >= n:
            raise IndexError(
                f"array index {index} out of range (length {n})")
        if self._backing is not None:
            self._backing[self._offset + index] = value
        else:
            self.elements[index] = value

    def display(self) -> str:
        """Render the array using the language's own literal syntax."""
        return "[" + ", ".join(self.get(i).display()
                               for i in range(self.sizeof)) + "]"


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
        return ObjectValue(ArrayValue(elems, arr.element_type))
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
        return value.width
    if isinstance(value, FloatValue):
        return value.width
    if isinstance(value, StrValue):
        return "str"
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
    if isinstance(value, EnumValue):
        return value.enum_type.name
    if isinstance(value, TypeValue):
        return "type"
    return "int"


_TYPE_ALIASES: dict[str, str] = {}
_USER_TYPES: set[str] = set()


def register_user_type(name: str):
    """Register a user-defined type name (struct, etc.)."""
    _USER_TYPES.add(name)


def register_type_alias(name: str, target: str):
    """Register a user-defined type alias."""
    _TYPE_ALIASES[name] = target


def resolve_type_alias(type_name: str) -> str:
    """Resolve type aliases transitively, returning the underlying type."""
    seen: set[str] = set()
    while type_name in _TYPE_ALIASES and type_name not in seen:
        seen.add(type_name)
        type_name = _TYPE_ALIASES[type_name]
    return type_name


def _parse_array_type(type_name: str) -> tuple[str, int | None] | None:
    """Parse an array type string, returning (element_type, size_or_None) or None."""
    import re
    m = re.fullmatch(r"(\w+)\[(\d+)?\]", type_name)
    if m is None:
        return None
    return m.group(1), int(m.group(2)) if m.group(2) else None


def validate_type(type_name: str) -> bool:
    """Return True if type_name is a known builtin type (with optional/expected/array modifiers)."""
    type_name = resolve_type_alias(type_name)
    if is_generic_type(type_name):
        return True
    base, opt_err = _split_optional_type(type_name)
    arr = _parse_array_type(base)
    if arr is not None:
        base = arr[0]
    base = resolve_type_alias(base)
    if base in BUILTIN_TYPES or base in _USER_TYPES:
        return True
    return False


def validate_param_type(param_type: str, func_name: str, param_name: str):
    """Validate that a parameter type annotation is a known builtin type."""
    if not validate_type(param_type):
        raise TypeError(
            f"in {func_name}: parameter '{param_name}' has unknown type '{param_type}'")


def coerce_arg(value: "Value", param_type: str, func_name: str, param_name: str) -> "Value":
    """Coerce a runtime argument to match a declared parameter type."""
    param_type = resolve_type_alias(param_type)
    if isinstance(value, UnitValue):
        value = value.inner
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

    if param_type == "str":
        if not isinstance(value, StrValue):
            raise TypeError(
                f"{func_name}: argument '{param_name}' expected str, "
                f"got {type(value).__name__}")
        return value

    if param_type == "\N{EMPTY SET}":
        if not isinstance(value, NoneValue):
            raise TypeError(
                f"{func_name}: argument '{param_name}' expected \N{EMPTY SET}, "
                f"got {type(value).__name__}")
        return value

    arr_info = _parse_array_type(param_type)
    if arr_info is not None:
        elem_type, expected_size = arr_info
        unwrapped = value
        if isinstance(value, SomeValue):
            unwrapped = value.value
        if isinstance(unwrapped, ObjectValue) and isinstance(unwrapped.obj, ArrayValue):
            if expected_size is not None and unwrapped.obj.sizeof != expected_size:
                raise TypeError(
                    f"{func_name}: argument '{param_name}' expected "
                    f"{param_type} (length {expected_size}), "
                    f"got array of length {unwrapped.obj.sizeof}")
            return unwrapped
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
            raise TypeError(
                f"{func_name}: argument '{param_name}' expected {param_type}, "
                f"got {type(value).__name__}")
        return coerce_to_type(value, param_type)

    if param_type in FLOAT_TYPES:
        if isinstance(value, IntValue):
            return mk_float(float(value.value), param_type)
        if isinstance(value, FloatValue):
            return mk_float(value.value, param_type)
        raise TypeError(
            f"{func_name}: argument '{param_name}' expected {param_type}, "
            f"got {type(value).__name__}")

    if is_generic_type(param_type):
        return value

    if param_type in _USER_TYPES:
        return value

    raise TypeError(
        f"{func_name}: argument '{param_name}' has unknown type '{param_type}'")


def coerce_to_type(value: Value, target_width: str) -> Value:
    """Coerce a value to a target integer type.

    For scalar IntValue, checks that the value fits the target type.
    For ObjectValue(ArrayValue), coerces each element and sets element_type.
    Returns the value unchanged if no coercion is needed.
    Raises OverflowError if the value does not fit.
    """
    target_width = resolve_type_alias(target_width)
    if target_width is None or target_width == "int":
        return value
    if not validate_type(target_width):
        raise TypeError(f"unknown type '{target_width}'")
    if isinstance(value, UnitValue):
        value = value.inner
    if isinstance(value, IntValue):
        if _is_unsigned(target_width):
            return IntValue(wrap_int(value.value, target_width), target_width)
        check_int(value.value, target_width)
        return IntValue(value.value, target_width)
    if isinstance(value, ObjectValue) and isinstance(value.obj, ArrayValue):
        arr = value.obj
        arr_info = _parse_array_type(target_width)
        elem_target = arr_info[0] if arr_info is not None else target_width
        coerced = [coerce_to_type(arr.get(i), elem_target) for i in range(arr.sizeof)]
        return ObjectValue(ArrayValue(coerced, element_type=elem_target))
    return value
