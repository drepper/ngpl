"""Turning a @repr(C) value into the bytes its layout describes.

A struct with a defined layout is a statement about bytes: where each
field sits and how wide it is.  `interp/layout.py` computes that
statement; this module carries it out, writing the field values into a
buffer of the struct's size with the skipped bytes left as zeros.

The point of it is `writev`.  A program that means to write a binary
format -- an ELF file, a wire packet, a device image -- should be able
to say what the format *is*, as structs with a layout, and then hand
those structs to the kernel rather than pushing bytes into an array by
hand.  Packing is what stands between the two.

Byte order is the target's, which is little-endian: the compiler
generates x86-64 and nothing here is asked to produce bytes for a
machine other than the one it runs on.  When a big-endian target
arrives this is the one place that has to learn about it.
"""

from interp.layout import (LayoutError, REPR_C, struct_lookup, struct_layout,
                           type_layout)
from interp.value import (_parse_array_type, enum_underlying_type,
                          is_enum_type, resolve_type_alias)

__all__ = ["pack_value", "iov_bytes", "collect_lookup", "PackError",
           "struct_lookup"]


class PackError(Exception):
    """Raised when a value cannot be written as the bytes of its type."""


def _int_bytes(n: int, size: int, signed: bool, what: str) -> bytes:
    """The little-endian encoding of n in `size` bytes.

    A value that does not fit is an error rather than a truncation: the
    whole reason to write bytes out is that something else will read
    them back, and a silently narrowed field is a corrupt file.
    """
    try:
        return int(n).to_bytes(size, "little", signed=signed)
    except OverflowError:
        raise PackError(
            f"{what}: {n} does not fit {size} byte"
            f"{'' if size == 1 else 's'}") from None


def _scalar_signed(type_name: str) -> bool:
    """Whether a scalar type name is a signed integer."""
    return type_name.startswith("i") and not type_name.startswith("is")


def pack_value(value, type_name: str, lookup, what: str = "field") -> bytes:
    """The bytes of one value, as its stated type lays it out.

    Args:
        value: the runtime Value (or raw object) to encode.
        type_name: the type the value was declared with.
        lookup: maps a struct name to its StructType, or returns None.
        what: names the thing being packed, for the diagnostic.

    Returns:
        Exactly `type_layout(type_name)[0]` bytes.
    """
    from interp.value import (ArrayValue, BoolValue, EnumValue, IntValue,
                              ObjectValue, UnitValue)

    inner = value
    while isinstance(inner, (UnitValue, ObjectValue)):
        inner = inner.inner if isinstance(inner, UnitValue) else inner.obj

    resolved = resolve_type_alias(type_name)

    nested = lookup(resolved)
    if nested is not None:
        return pack_struct(inner, lookup)

    array = _parse_array_type(resolved)
    if array is not None:
        element, dims = array
        if any(d is None for d in dims):
            raise PackError(f"{what}: '{type_name}' leaves a dimension open")
        count = 1
        for d in dims:
            count *= d
        if not isinstance(inner, ArrayValue):
            raise PackError(f"{what}: expected an array of {count}")
        if len(inner.elements) != count:
            raise PackError(
                f"{what}: the type says {count} element"
                f"{'' if count == 1 else 's'}, the value has "
                f"{len(inner.elements)}")
        out = bytearray()
        for element_value in inner.elements:
            out += pack_value(element_value, element, lookup, what)
        return bytes(out)

    if is_enum_type(resolved):
        under = enum_underlying_type(resolved) or "u64"
        size, _ = type_layout(under, lookup)
        raw = inner.value if isinstance(inner, EnumValue) else inner
        if isinstance(raw, IntValue):
            raw = raw.value
        return _int_bytes(raw, size, _scalar_signed(under), what)

    if resolved == "bool":
        if not isinstance(inner, BoolValue):
            raise PackError(f"{what}: expected a truth value")
        return b"\x01" if inner.value else b"\x00"

    size, _ = type_layout(resolved, lookup)
    if isinstance(inner, IntValue):
        return _int_bytes(inner.value, size, _scalar_signed(resolved), what)
    if isinstance(inner, int):
        return _int_bytes(inner, size, _scalar_signed(resolved), what)
    raise PackError(f"{what}: {resolved} is not a value this writes out")


def pack_struct(instance, lookup) -> bytes:
    """The bytes of a @repr(C) struct instance, padding included.

    The buffer starts as zeros and each field is written at its offset,
    so the padding a layout leaves is written out as zeros rather than
    as whatever happened to be in memory -- a file that is the same
    every time it is produced is worth more than the cycles saved.
    """
    from interp.value import StructInstance

    if not isinstance(instance, StructInstance):
        raise PackError("only a struct with a defined layout writes out as "
                        "bytes")
    stype = instance.struct_type
    if stype.repr_kind != REPR_C:
        raise PackError(
            f"struct '{stype.name}' has no defined layout; annotate it with "
            f"@repr(C) to give it one")
    layout = struct_layout(stype, lookup)
    out = bytearray(layout.size)
    for field in layout.fields:
        value = instance.field_values.get(field.name)
        if value is None:
            raise PackError(f"struct '{stype.name}' has no field "
                            f"'{field.name}' to write")
        raw = pack_value(value, field.type_name, lookup,
                         f"{stype.name}.{field.name}")
        out[field.offset:field.offset + len(raw)] = raw
    return bytes(out)


def iov_bytes(part, lookup, index: int) -> bytes:
    """The bytes one run of a `writev` holds.

    A run is made from one of three things: a byte array, which is
    already its own bytes; a @repr(C) struct, which is packed; or an
    array of @repr(C) structs -- a table, such as a section header
    table -- which is packed element after element, exactly as C lays
    an array out.
    """
    from interp.value import (ArrayValue, IntValue, ObjectValue,
                              StructInstance, UnitValue)

    _ = index
    inner = part
    while isinstance(inner, (UnitValue, ObjectValue)):
        inner = inner.inner if isinstance(inner, UnitValue) else inner.obj

    if isinstance(inner, (bytes, bytearray)):
        return bytes(inner)

    if isinstance(inner, StructInstance):
        return pack_struct(inner, lookup)

    if isinstance(inner, ArrayValue):
        out = bytearray()
        for element in inner.elements:
            value = element
            while isinstance(value, (UnitValue, ObjectValue)):
                value = (value.inner if isinstance(value, UnitValue)
                         else value.obj)
            if isinstance(value, StructInstance):
                out += pack_struct(value, lookup)
                continue
            if isinstance(value, IntValue):
                if value.value < 0 or value.value > 255:
                    raise PackError(
                        f"{value.value} does not fit a byte")
                out.append(value.value)
                continue
            raise PackError(
                f"an array written out holds bytes or structs with a "
                f"defined layout, not {type(value).__name__}")
        return bytes(out)

    raise PackError(
        "a run of bytes is made from bytes, a struct with a defined layout, "
        "or an array of them")


def collect_lookup(parts):
    """A struct-name resolver built from the values about to be packed.

    `struct_layout` resolves a nested struct field by name, which
    normally means asking the environment.  Nothing needs to be asked
    here: a nested field that has a layout also has a value, and that
    value carries its own StructType.  Walking the pieces therefore
    finds every type the layout of those pieces can mention, and
    `writev` stays a method on the file rather than something that has
    to reach back into the evaluator for its environment.
    """
    from interp.value import (ArrayValue, ObjectValue, StructInstance,
                              UnitValue)

    found: dict = {}

    def visit(value, depth: int):
        if depth > 64:
            return
        while isinstance(value, (UnitValue, ObjectValue)):
            value = value.inner if isinstance(value, UnitValue) else value.obj
        if isinstance(value, StructInstance):
            found.setdefault(value.struct_type.name, value.struct_type)
            for field_value in value.field_values.values():
                visit(field_value, depth + 1)
        elif isinstance(value, ArrayValue):
            for element in value.elements:
                visit(element, depth + 1)

    for part in parts:
        visit(part, 0)
    return found.get


def _unused():
    """Keep LayoutError and struct_lookup referenced for re-export."""
    return LayoutError, struct_lookup
