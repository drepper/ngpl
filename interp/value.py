"""Runtime value types for the newlang language.

Each runtime value is wrapped in one of these classes. The evaluator
operates on these values rather than raw Python objects to support
type checking and proper error messages.
"""


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

    def __init__(self, value: int, width: str = "i64"):
        self.value = value  # Python int (unbounded, but clamped to width in strict mode)
        self.width = width  # type string like "i32", "u64"

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


class ArrayValue(Value):
    """A mutable array of runtime Values with dynamic growth.

    Elements can be read via get() and written via set().
    Setting an index beyond the current length zero-fills the gap.
    """

    __slots__ = ("elements",)

    def __init__(self, elements=None):
        self.elements = list(elements) if elements else []

    def get(self, index: int) -> Value:
        """Return element at index; returns IntValue(0) if out of range."""
        if 0 <= index < len(self.elements):
            return self.elements[index]
        return mk_int(0)

    def set(self, index: int, value: Value):
        """Set element at index. Grows the array with zero-fill as needed."""
        while len(self.elements) <= index:
            self.elements.append(mk_int(0))
        self.elements[index] = value


def mk_int(value, width="i64"):
    """Create an IntValue."""
    return IntValue(value, width)


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
