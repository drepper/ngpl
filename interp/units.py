"""Unit system for dimensional analysis in newlang.

Provides Unit class for tracking physical dimensions and conversion factors,
with builtin SI units, byte units, and abstract units.
"""

from fractions import Fraction
import math


class Unit:
    """A physical unit with dimensions and conversion factor.

    components maps base dimension names to integer exponents.
    factor is a Fraction: 1 of this unit = factor of the base representation.
    """

    __slots__ = ("components", "factor", "display_name")

    def __init__(self, components: dict[str, int], factor: Fraction,
                 display_name: str):
        self.components = components
        self.factor = factor
        self.display_name = display_name

    def same_dimension(self, other: "Unit") -> bool:
        a = {k: v for k, v in self.components.items() if v != 0}
        b = {k: v for k, v in other.components.items() if v != 0}
        return a == b

    def is_dimensionless(self) -> bool:
        return all(v == 0 for v in self.components.values())

    def base_form(self) -> "Unit":
        components = {k: v for k, v in self.components.items() if v != 0}
        return Unit(components, Fraction(1), _display_from_components(components))

    def __mul__(self, other: "Unit") -> "Unit":
        components = dict(self.components)
        for k, v in other.components.items():
            components[k] = components.get(k, 0) + v
        return Unit(components, self.factor * other.factor,
                    f"{self.display_name}*{other.display_name}")

    def __truediv__(self, other: "Unit") -> "Unit":
        components = dict(self.components)
        for k, v in other.components.items():
            components[k] = components.get(k, 0) - v
        return Unit(components, self.factor / other.factor,
                    f"{self.display_name}/{other.display_name}")

    def sqrt(self) -> "Unit":
        for k, v in self.components.items():
            if v != 0 and v % 2 != 0:
                raise TypeError(
                    f"cannot take square root of unit {self.display_name}: "
                    f"dimension '{k}' has odd exponent {v}")
        components = {k: v // 2 for k, v in self.components.items()}
        num_root = _isqrt_exact(self.factor.numerator)
        den_root = _isqrt_exact(self.factor.denominator)
        if num_root is None or den_root is None:
            raise TypeError(
                f"cannot take square root of unit {self.display_name}: "
                f"factor {self.factor} is not a perfect square")
        return Unit(components, Fraction(num_root, den_root),
                    f"\N{SQUARE ROOT}{self.display_name}")

    def __eq__(self, other):
        if not isinstance(other, Unit):
            return NotImplemented
        a = {k: v for k, v in self.components.items() if v != 0}
        b = {k: v for k, v in other.components.items() if v != 0}
        return a == b and self.factor == other.factor

    def __hash__(self):
        return hash((tuple(sorted(
            (k, v) for k, v in self.components.items() if v != 0
        )), self.factor))


def _isqrt_exact(n: int) -> int | None:
    if n < 0:
        return None
    if n == 0:
        return 0
    r = math.isqrt(n)
    return r if r * r == n else None


_DIMENSION_ABBREV: dict[str, str] = {
    "meter": "m",
    "second": "s",
    "kilogram": "kg",
    "ampere": "A",
    "kelvin": "K",
    "mole": "mol",
    "candela": "cd",
    "byte": "B",
    "count": "count",
    "distance": "distance",
}


def _display_from_components(components: dict[str, int]) -> str:
    if not components:
        return "1"
    pos = sorted((k, v) for k, v in components.items() if v > 0)
    neg = sorted((k, -v) for k, v in components.items() if v < 0)
    num_parts: list[str] = []
    for name, exp in pos:
        abbr = _DIMENSION_ABBREV.get(name, name)
        num_parts.append(abbr if exp == 1 else f"{abbr}^{exp}")
    den_parts: list[str] = []
    for name, exp in neg:
        abbr = _DIMENSION_ABBREV.get(name, name)
        den_parts.append(abbr if exp == 1 else f"{abbr}^{exp}")
    if num_parts and den_parts:
        return "*".join(num_parts) + "/" + "*".join(den_parts)
    if num_parts:
        return "*".join(num_parts)
    if den_parts:
        return "1/" + "*".join(den_parts)
    return "1"


# ---------------------------------------------------------------------------
# Builtin unit registry
# ---------------------------------------------------------------------------

BUILTIN_UNITS: dict[str, Unit] = {}
USER_UNITS: dict[str, Unit] = {}


def _reg(name: str, components: dict[str, int], factor: Fraction, display: str):
    BUILTIN_UNITS[name] = Unit(components, factor, display)


# SI base units
_reg("meter", {"meter": 1}, Fraction(1), "m")
_reg("second", {"second": 1}, Fraction(1), "s")
_reg("kilogram", {"kilogram": 1}, Fraction(1), "kg")
_reg("ampere", {"ampere": 1}, Fraction(1), "A")
_reg("kelvin", {"kelvin": 1}, Fraction(1), "K")
_reg("mole", {"mole": 1}, Fraction(1), "mol")
_reg("candela", {"candela": 1}, Fraction(1), "cd")

# SI derived: length
_reg("kilometer", {"meter": 1}, Fraction(1000), "km")
_reg("centimeter", {"meter": 1}, Fraction(1, 100), "cm")
_reg("millimeter", {"meter": 1}, Fraction(1, 1000), "mm")
_reg("micrometer", {"meter": 1}, Fraction(1, 1_000_000), "\N{GREEK SMALL LETTER MU}m")
_reg("nanometer", {"meter": 1}, Fraction(1, 1_000_000_000), "nm")

# SI derived: time
_reg("millisecond", {"second": 1}, Fraction(1, 1000), "ms")
_reg("microsecond", {"second": 1}, Fraction(1, 1_000_000), "\N{GREEK SMALL LETTER MU}s")
_reg("nanosecond", {"second": 1}, Fraction(1, 1_000_000_000), "ns")
_reg("minute", {"second": 1}, Fraction(60), "min")
_reg("hour", {"second": 1}, Fraction(3600), "h")

# SI derived: mass
_reg("gram", {"kilogram": 1}, Fraction(1, 1000), "g")
_reg("milligram", {"kilogram": 1}, Fraction(1, 1_000_000), "mg")

# SI derived: combined
_reg("newton", {"kilogram": 1, "meter": 1, "second": -2}, Fraction(1), "N")
_reg("pascal", {"kilogram": 1, "meter": -1, "second": -2}, Fraction(1), "Pa")
_reg("joule", {"kilogram": 1, "meter": 2, "second": -2}, Fraction(1), "J")
_reg("watt", {"kilogram": 1, "meter": 2, "second": -3}, Fraction(1), "W")
_reg("hertz", {"second": -1}, Fraction(1), "Hz")
_reg("volt", {"kilogram": 1, "meter": 2, "second": -3, "ampere": -1}, Fraction(1), "V")
_reg("coulomb", {"ampere": 1, "second": 1}, Fraction(1), "C")

# Byte units (SI and binary prefixes)
_reg("byte", {"byte": 1}, Fraction(1), "B")
_reg("kilobyte", {"byte": 1}, Fraction(1000), "kB")
_reg("kibibyte", {"byte": 1}, Fraction(1024), "KiB")
_reg("megabyte", {"byte": 1}, Fraction(1_000_000), "MB")
_reg("mebibyte", {"byte": 1}, Fraction(1_048_576), "MiB")
_reg("gigabyte", {"byte": 1}, Fraction(1_000_000_000), "GB")
_reg("gibibyte", {"byte": 1}, Fraction(1_073_741_824), "GiB")
_reg("terabyte", {"byte": 1}, Fraction(1_000_000_000_000), "TB")
_reg("tebibyte", {"byte": 1}, Fraction(1_099_511_627_776), "TiB")

# Abstract units
_reg("count", {"count": 1}, Fraction(1), "count")
_reg("distance", {"distance": 1}, Fraction(1), "distance")
_reg("ptrdiff", {"ptrdiff": 1}, Fraction(1), "ptrdiff")


# ---------------------------------------------------------------------------
# Unit formula evaluation
# ---------------------------------------------------------------------------

def eval_unit_formula(node) -> Unit:
    """Evaluate a unit formula AST node to a Unit."""
    from interp.ast import UnitName, UnitLit, UnitBinOp, UnitSqrt
    if isinstance(node, UnitName):
        if node.is_string:
            if node.name in USER_UNITS:
                return USER_UNITS[node.name]
            raise TypeError(f"unknown unit \"{node.name}\"")
        if node.name in BUILTIN_UNITS:
            return BUILTIN_UNITS[node.name]
        if node.name in USER_UNITS:
            return USER_UNITS[node.name]
        raise TypeError(f"unknown unit '{node.name}'")
    if isinstance(node, UnitLit):
        return Unit({}, Fraction(node.value), str(node.value))
    if isinstance(node, UnitBinOp):
        left = eval_unit_formula(node.left)
        right = eval_unit_formula(node.right)
        if node.op == "*":
            return left * right
        if node.op == "/":
            return left / right
        raise TypeError(f"unknown unit operator '{node.op}'")
    if isinstance(node, UnitSqrt):
        operand = eval_unit_formula(node.operand)
        return operand.sqrt()
    raise TypeError(f"unexpected unit formula node: {type(node).__name__}")


def register_user_unit(name: str, unit: Unit):
    """Register a user-defined unit."""
    USER_UNITS[name] = unit
