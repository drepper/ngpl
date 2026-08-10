"""C-compatible layout computation for @repr(C) product types.

A struct without a layout attribute has no defined layout: the
implementation may reorder its fields and choose its padding freely, so
asking where a field sits is not a meaningful question.  @repr(C) gives
up that freedom in exchange for a layout that matches what a C compiler
would produce for the same declaration, which is what calling a foreign
function requires.

The rules implemented here are those of the System V AMD64 psABI, which
are also the rules of every other mainstream C ABI for these types:

  * fields are placed in declaration order;
  * each field starts at the next offset that is a multiple of its own
    alignment, with the skipped bytes becoming padding;
  * the struct's alignment is the largest alignment among its fields;
  * the struct's size is rounded up to a multiple of that alignment, so
    that an array of the struct keeps every element aligned.

Only types with a defined C representation may appear in a @repr(C)
struct.  The language's unsized types -- `int` and `float`, which are
arbitrary-precision -- have none, and neither do `str`, optionals, or
dynamically sized arrays, which are not plain sequences of bytes.
"""

from interp.value import (_TYPE_BITS, _parse_array_type, resolve_type_alias,
                          is_enum_type, enum_underlying_type)

# Size and alignment in bytes for each scalar type with a C counterpart.
# Sub-word integers align to their own width, which is what the psABI
# specifies and what every C compiler on the platform does.
_SCALAR_LAYOUT: dict[str, tuple[int, int]] = {
    "bool": (1, 1),
    "i8": (1, 1), "u8": (1, 1), "byte": (1, 1),
    "i16": (2, 2), "u16": (2, 2),
    "f16": (2, 2), "bfloat16": (2, 2),
    "i32": (4, 4), "u32": (4, 4), "f32": (4, 4),
    "i64": (8, 8), "u64": (8, 8), "f64": (8, 8),
    "usize": (8, 8),
}

# The unsized types, named separately so the diagnostic can say why they
# are rejected rather than merely that they are unknown.
_UNSIZED_TYPES = frozenset({"int", "float"})

REPR_C = "C"
KNOWN_REPRS = frozenset({REPR_C})


class LayoutError(Exception):
    """Raised when a layout cannot be computed for a type."""


class FieldLayout:
    """Where a single field sits within its struct."""

    __slots__ = ("name", "type_name", "offset", "size", "align")

    def __init__(self, name: str, type_name: str, offset: int, size: int,
                 align: int):
        self.name = name
        self.type_name = type_name
        self.offset = offset
        self.size = size
        self.align = align


class StructLayout:
    """The computed layout of a @repr(C) struct."""

    __slots__ = ("size", "align", "fields")

    def __init__(self, size: int, align: int, fields: list[FieldLayout]):
        self.size = size
        self.align = align
        self.fields = fields

    def offset_of(self, name: str) -> int:
        """Return the byte offset of a named field.

        Raises:
            LayoutError: when the struct has no such field.
        """
        for field in self.fields:
            if field.name == name:
                return field.offset
        raise LayoutError(f"no field '{name}'")


def struct_lookup(env):
    """Build the struct-name resolver that the layout functions expect.

    Args:
        env: the environment holding the struct definitions.

    Returns:
        A callable mapping a name to its StructType, or None when the
        name is not a struct.
    """
    from interp.value import StructType

    def lookup(name: str):
        try:
            value = env.lookup(name)
        except KeyError:
            return None
        return value if isinstance(value, StructType) else None

    return lookup


def _align_up(value: int, alignment: int) -> int:
    """Round value up to the next multiple of alignment."""
    return (value + alignment - 1) // alignment * alignment


def _fast_type_layout(type_name: str) -> tuple[int, int] | None:
    """Size and alignment of a fast integer type, or None if not one.

    A fast type's width is platform-defined but concrete, so it has a
    layout even though its name does not state a width.
    """
    if not type_name.endswith("fast"):
        return None
    bits = _TYPE_BITS.get(type_name)
    if bits is None:
        return None
    return bits // 8, bits // 8


# The widths C has a type for.  A width outside these has no C
# counterpart, so a @repr(C) struct cannot hold one.
_C_INTEGER_WIDTHS = frozenset({8, 16, 32, 64})


def _stated_width_layout(type_name: str, c_compatible: bool
                         ) -> tuple[int, int] | None:
    """Size and alignment of an integer type that states its width.

    The storage is the whole bytes it takes to hold the width, and the
    alignment is the largest power of two those bytes reach, capped at
    the platform's own.  A width C has no type for is refused where a C
    layout is what was asked for.
    """
    from interp.value import _parse_int_width
    bits = _parse_int_width(type_name)
    if bits is None:
        return None
    if c_compatible and bits not in _C_INTEGER_WIDTHS:
        raise LayoutError(
            f"type '{type_name}' has no C counterpart: C has an integer "
            f"type of 8, 16, 32, or 64 bits, not {bits}")
    size = (bits + 7) // 8
    align = 1
    while align * 2 <= size and align < 8:
        align *= 2
    return size, align


def type_layout(type_name: str, lookup, seen: frozenset[str] = frozenset(),
                c_compatible: bool = True) -> tuple[int, int]:
    """Compute the size and alignment in bytes of a field type.

    Args:
        type_name: the declared type of the field.
        lookup: maps a struct name to its StructType, or returns None.
        seen: struct names already being laid out, to catch recursion.

    Returns:
        A (size, align) pair in bytes.

    Raises:
        LayoutError: when the type has no defined C representation.
    """
    resolved = resolve_type_alias(type_name)

    if resolved in _SCALAR_LAYOUT:
        return _SCALAR_LAYOUT[resolved]

    stated = _stated_width_layout(resolved, c_compatible)
    if stated is not None:
        return stated

    fast = _fast_type_layout(resolved)
    if fast is not None:
        return fast

    if resolved in _UNSIZED_TYPES:
        raise LayoutError(
            f"type '{type_name}' is arbitrary-precision and has no defined C "
            f"representation; use a sized type such as "
            f"{'i64' if resolved == 'int' else 'f64'}")

    if resolved.endswith("?") or "?" in resolved:
        raise LayoutError(
            f"optional type '{type_name}' has no defined C representation")

    if resolved == "str":
        raise LayoutError(
            "type 'str' has no defined C representation; use a sized byte "
            "array such as u8[16]")

    # An enum is stored as an integer, so it lays out as that integer.
    if is_enum_type(resolved):
        return type_layout(enum_underlying_type(resolved), lookup, seen)

    array = _parse_array_type(resolved)
    if array is not None:
        element, dims = array
        if any(d is None for d in dims):
            if c_compatible:
                raise LayoutError(
                    f"dynamically sized array '{type_name}' has no defined C "
                    f"representation; give it a fixed size")
            raise LayoutError(
                f"'{type_name}' leaves a dimension open, so how much it "
                f"occupies is not part of its type; give every dimension a "
                f"size, or ask a value with .sizeof")
        size, align = type_layout(element, lookup, seen, c_compatible)
        # A multi-dimensional array lays out as C's T[n][m]: the rows sit
        # one after another, so the alignment is still the element's.
        for count in dims:
            size *= count
        return size, align

    nested = lookup(resolved)
    if nested is not None:
        layout = struct_layout(nested, lookup, seen)
        return layout.size, layout.align

    raise LayoutError(f"type '{type_name}' has no defined C representation")


def struct_layout(struct_type, lookup, seen: frozenset[str] = frozenset()
                  ) -> StructLayout:
    """Compute the C layout of a struct.

    Args:
        struct_type: the StructType to lay out.
        lookup: maps a struct name to its StructType, or returns None.
        seen: struct names already being laid out, to catch recursion.

    Returns:
        The StructLayout, with a FieldLayout for every field.

    Raises:
        LayoutError: when the struct is not @repr(C), contains a field
            with no C representation, or contains itself.
    """
    if struct_type.repr_kind != REPR_C:
        raise LayoutError(
            f"struct '{struct_type.name}' has no defined layout; annotate it "
            f"with @repr(C) to give it one")

    if struct_type.name in seen:
        raise LayoutError(
            f"struct '{struct_type.name}' contains itself, so it has no "
            f"finite layout")
    seen = seen | {struct_type.name}

    offset = 0
    align = 1
    fields: list[FieldLayout] = []
    for field_name, field_type in struct_type.fields:
        try:
            size, field_align = type_layout(field_type, lookup, seen)
        except LayoutError as e:
            raise LayoutError(
                f"in @repr(C) struct '{struct_type.name}', field "
                f"'{field_name}': {e}")
        offset = _align_up(offset, field_align)
        fields.append(FieldLayout(field_name, field_type, offset, size,
                                  field_align))
        offset += size
        align = max(align, field_align)

    # An empty struct occupies no space, as in C.  C++ would give it one
    # byte so that distinct objects have distinct addresses; the language
    # has no such requirement here.
    return StructLayout(_align_up(offset, align), align, fields)
