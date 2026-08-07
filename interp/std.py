"""Standard library (std) runtime.

Implements the built-in modules available to all NGPL programs.
Uses direct system calls via ctypes where Python's os module does not
expose sufficient low-level control.

The std object exposes:
    fs.cwd()          → DirFD wrapper (opens current dir with O_DIRECTORY)
    heap              → Allocator management (mmap-backed)
    args              → Command line parameters of the running program
    env               → Read access to the process environment
    sys               → CPU affinity, CPU counts, and memory sizes
    sha256(data)      → SHA-256 hash as IntValue (arbitrary-width int)
    format(str, file?, fd?) → Format a string, optionally write to a file descriptor
    get_stdout()      → StdoutFile object wrapping stdout fd

All filesystem operations use AT_FDCWD or explicit dirfd — no bare path
operations that would bypass the kernel's directory-based interfaces.
"""

import ctypes
import ctypes.util
import hashlib
import mmap
import os
import sys


# ---------------------------------------------------------------------------
# Constants (Linux x86_64)
# ---------------------------------------------------------------------------

libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
AT_FDCWD = -100  # current working directory for openat
O_RDONLY = 0
O_DIRECTORY = 0o200000  # must be a directory
S_IRUSR = 0o400       # user read
S_IWUSR = 0o200       # user write
EINVAL = 22           # invalid argument

# sysconf(3) selectors (glibc bits/confname.h)
_SC_PAGESIZE = 30
_SC_NPROCESSORS_CONF = 83
_SC_NPROCESSORS_ONLN = 84
_SC_PHYS_PAGES = 85


# ---------------------------------------------------------------------------
# Low-level libc wrappers
# ---------------------------------------------------------------------------

_openat = libc.openat
_openat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
_openat.restype = ctypes.c_int

_getdents64 = libc.syscall
_getdents64.argtypes = [ctypes.c_long, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
_getdents64.restype = ctypes.c_long

_close = libc.close
_close.argtypes = [ctypes.c_int]
_close.restype = ctypes.c_int

_sysconf = libc.sysconf
_sysconf.argtypes = [ctypes.c_int]
_sysconf.restype = ctypes.c_long

_getenv = libc.getenv
_getenv.argtypes = [ctypes.c_char_p]
_getenv.restype = ctypes.c_char_p

_sched_getaffinity = libc.sched_getaffinity
_sched_getaffinity.argtypes = [ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p]
_sched_getaffinity.restype = ctypes.c_int


def _decode(raw: bytes) -> str:
    """Decode a NUL-terminated C string from the environment as UTF-8.

    The language mandates UTF-8 throughout, but the process environment
    is supplied by the operating system and carries no such guarantee.
    Invalid byte sequences are replaced with U+FFFD rather than raising,
    so a single malformed variable cannot make the environment
    unreadable as a whole.
    """
    return raw.decode("utf-8", errors="replace")


def _environ_entries() -> list[str]:
    """Read the process environment directly from the libc environ array.

    Returns:
        The raw "NAME=VALUE" entries, in the order the kernel supplied
        them on the initial stack.
    """
    entries: list[str] = []
    block = ctypes.POINTER(ctypes.c_char_p).in_dll(libc, "environ")
    if not block:
        return entries
    i = 0
    while block[i] is not None:
        entries.append(_decode(block[i]))
        i += 1
    return entries


def _affinity_mask() -> int:
    """Read the calling thread's CPU affinity mask via sched_getaffinity.

    The mask size is not known in advance, so the buffer starts at 128
    bytes (1024 CPUs) and doubles on EINVAL, which is how the kernel
    reports that the supplied cpu_set_t was too small.

    Returns:
        The affinity mask as a non-negative integer whose bit *n* is set
        when CPU *n* is available to this thread.
    """
    size = 128
    while size <= 1 << 20:
        buf = ctypes.create_string_buffer(size)
        if _sched_getaffinity(0, size, buf) == 0:
            return int.from_bytes(buf.raw, "little")
        errno = ctypes.get_errno()
        if errno != EINVAL:
            raise OSError(
                f"sched_getaffinity: {os.strerror(errno)} (errno={errno})")
        size *= 2
    raise OSError("sched_getaffinity: affinity mask exceeds 8388608 CPUs")


def _checked_sysconf(name: int, what: str) -> int:
    """Query sysconf and reject the -1 "unsupported or unlimited" answer."""
    ctypes.set_errno(0)
    value = _sysconf(name)
    if value < 0:
        errno = ctypes.get_errno()
        if errno != 0:
            raise OSError(f"sysconf({what}): {os.strerror(errno)} (errno={errno})")
        raise OSError(f"sysconf({what}): value is indeterminate on this system")
    return value


# ---------------------------------------------------------------------------
# Value-level wrapper for a directory fd (opened with O_DIRECTORY)
# ---------------------------------------------------------------------------

class DirFD:
    """Wrapper around a file descriptor opened as a directory.

    Provides openFile() which calls openat(dirfd, pathname, flags).
    The raw fd is accessible via .fd for direct use in the language.
    """

    __slots__ = ("_fd",)

    def __init__(self, fd: int):
        self._fd = fd

    @property
    def fd(self) -> int:
        """The underlying directory file descriptor number."""
        return self._fd

    def open_file(self, name, mode=None, flags=None):
        """Open a file relative to this directory using openat.

        Args:
            name: filename (str or bytes).
            mode: POSIX mode bits (default 0o644).
            flags: openat flags (default O_RDONLY | O_CLOEXEC).

        Returns:
            FileStream wrapping the new file descriptor.
        """
        if isinstance(name, str):
            name = name.encode("utf-8")
        if mode is None:
            mode = S_IRUSR | S_IWUSR
        if flags is None:
            flags = O_RDONLY | 0o1000000  # O_CLOEXEC = 0o1000000
        fd = _openat(self._fd, name, flags)
        if fd < 0:
            errno = ctypes.get_errno()
            raise OSError(f"openat({self._fd}, {name!r}): {os.strerror(errno)} (errno={errno})")
        return FileStream(fd)

    # Alias for the language-level name (camelCase).
    openFile = open_file


# ---------------------------------------------------------------------------
# File stream wrapper
# ---------------------------------------------------------------------------

class FileStream:
    """Wrapper around an opened file descriptor.

    Provides read_file() which reads the entire file content into
    allocated memory using the provided allocator, then returns the
    result as a Bytes object containing the raw data.
    """

    __slots__ = ("_fd",)

    def __init__(self, fd: int):
        self._fd = fd

    @property
    def fd(self) -> int:
        return self._fd

    def read_file(self, allocator):
        """Read the entire file content using the given allocator.

        Steps:
            1. Get file size via fstat (syscall).
            2. Allocate 'size' bytes from the allocator.
            3. Read all data into the allocated buffer.
            4. Return byte[] ArrayValue.

        Args:
            allocator: an MmapAllocator instance.

        Returns:
            An ObjectValue wrapping an ArrayValue of byte elements.
        """
        from interp.value import ObjectValue, ArrayValue, mk_int

        fsize = _get_file_size(self._fd)
        buf_result = allocator.alloc(fsize)

        if buf_result is None or buf_result.data is None:
            raise MemoryError("allocation failed in read_file")

        pos = 0
        total_read = 0
        while total_read < fsize:
            remaining = fsize - total_read
            if remaining > 65536:
                to_read = 65536
            else:
                to_read = remaining
            n = os.read(self._fd, to_read)
            if not n:
                break
            buf_result.data[pos:pos + len(n)] = n
            pos += len(n)
            total_read += len(n)

        raw = bytes(buf_result.data[:total_read])
        elements = [mk_int(b, "byte") for b in raw]
        return ObjectValue(ArrayValue(elements, element_type="byte"))

    def close(self):
        """Close the file descriptor."""
        _close(self._fd)


# ---------------------------------------------------------------------------
# Bytes — result of allocator.alloc() / file.read_file()
# ---------------------------------------------------------------------------

class Bytes:
    """Container for allocated byte data.

    Returned by allocator.alloc(size) and file.read_file().
    The caller (evaluator or std functions) converts this to StrValue
    as needed.
    """

    __slots__ = ("data", "size")

    def __init__(self, data: bytearray):
        self.data = data
        self.size = len(data)

    def getbyte(self, args):
        """getbyte(pos) — extract byte at index as an IntValue (0–255).

        Args:
            args[0]: IntValue — byte offset.

        Returns:
            IntValue with the byte value, or 0 if out of range.
        """
        from interp.eval import unwrap_optional
        from interp.value import mk_int
        if len(args) != 1:
            raise TypeError("getbyte(pos) takes exactly 1 argument")
        pos = int(unwrap_optional(args[0]).value)
        buf = bytes(self.data)
        if pos < 0 or pos >= len(buf):
            return mk_int(0)
        return mk_int(buf[pos])

    def getword(self, args):
        """getword(byte_offset) — extract big-endian 32-bit word as IntValue.

        Args:
            args[0]: IntValue — byte offset (must be aligned).

        Returns:
            IntValue with the unsigned 32-bit word, or 0 if out of range.
        """
        from interp.eval import unwrap_optional
        from interp.value import mk_int
        if len(args) != 1:
            raise TypeError("getword(off) takes exactly 1 argument")
        off = int(unwrap_optional(args[0]).value)
        buf = bytes(self.data)
        if off < 0 or off + 4 > len(buf):
            return mk_int(0)
        w = (buf[off] << 24) | (buf[off + 1] << 16) | (buf[off + 2] << 8) | buf[off + 3]
        return mk_int(w & 0xffffffff)


# ---------------------------------------------------------------------------
# Mmap-backed allocator
# ---------------------------------------------------------------------------

class MmapAllocator:
    """Memory allocator backed by mmap().

    Reserves large memory regions and allocates fixed-size blocks from them.
    Uses a simple bump-allocator strategy (no free — suitable for prototype).

    The mmap is MAP_PRIVATE | MAP_ANONYMOUS, so it does not map any file
    and creates private zero-initialized memory.
    """

    MAP_PRIVATE = 2
    MAP_ANONYMOUS = 0x20
    PROT_READ = 1
    PROT_WRITE = 2

    __slots__ = ("_regions", "_offsets", "_current_region", "_bytes_allocated")

    def __init__(self):
        self._regions = []         # list of mmap objects
        self._offsets = []         # next free offset within each region
        self._current_region = 0   # index into regions list
        self._bytes_allocated = 0

    def _ensure_region(self, size: int):
        """Ensure the current mmap region has enough space for 'size' bytes.

        Creates a new MAP_PRIVATE | MAP_ANONYMOUS mapping if needed.
        Each region is at least 4 MiB (or larger if size exceeds that).
        """
        desired = max(4 * 1024 * 1024, ((size + 4095) // 4096) * 4096)
        try:
            region = mmap.mmap(-1, desired, mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
                               self.PROT_READ | self.PROT_WRITE)
            self._regions.append(region)
            self._offsets.append(0)
        except OSError as e:
            raise MemoryError(f"mmap failed: {e}")

    def alloc(self, size: int):
        """Allocate 'size' bytes from the mmap pool.

        Args:
            size: number of bytes to allocate.

        Returns:
            A Bytes object with allocated data, or None if allocation fails.
        """
        if size <= 0:
            return Bytes(bytearray(0))

        # Try current region first.
        while self._current_region < len(self._regions):
            offset = self._offsets[self._current_region]
            remaining = len(self._regions[self._current_region]) - offset
            if remaining >= size:
                # Allocate from this region.
                region = self._regions[self._current_region]
                buf = bytearray(size)
                region[offset:offset + size] = buf
                self._offsets[self._current_region] += size
                self._bytes_allocated += size
                return Bytes(bytearray(buf))
            # Exhausted this region, try next.
            self._current_region += 1

        # Need a new region.
        self._ensure_region(size)
        region = self._regions[self._current_region]
        buf = bytearray(size)
        region[0:size] = buf
        self._offsets[self._current_region] += size
        self._bytes_allocated += size
        return Bytes(bytearray(buf))


# ---------------------------------------------------------------------------
# Utility: get file size via fstat (uses fd, no path resolution)
# ---------------------------------------------------------------------------

def _get_file_size(fd):
    """Get file size in bytes using the fstat syscall.

    Uses os.fstat which internally calls the fstat64 system call on Linux.
    This operates directly on a file descriptor — no path resolution is
    involved, consistent with the AT_FDCWD design principle.

    Args:
        fd: file descriptor (opened via openat or equivalent).

    Returns:
        File size as int, or 0 if unable to determine.
    """
    try:
        import struct
        # fstat64 on x86_64 Linux returns a struct stat with st_size at offset 116.
        # We use the lower-level __fxstat64 from glibc directly for clarity,
        # but os.fstat already provides this via ctypes internally.
        result = os.fstat(fd)
        return result.st_size
    except OSError:
        # Fallback: seek to end to discover size.
        try:
            current = os.lseek(fd, 0, os.SEEK_CUR)
            end = os.lseek(fd, 0, os.SEEK_END)
            os.lseek(fd, current, os.SEEK_SET)
            return end
        except OSError:
            return 0


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format_string(template, *args):
    """Format a string with optional arguments.

    Supports %s (string), %d (int), %x (hex), %X (uppercase hex).
    The template is a NGPL StrValue; args are runtime Values.

    Args:
        template: format string (StrValue or Python str).
        *args: values to substitute.

    Returns:
        A StrValue with the formatted result.
    """
    if isinstance(template, str):
        fmt = template
    else:
        fmt = template.value

    converted = []
    for arg in args:
        if hasattr(arg, "to_python"):
            converted.append(arg.to_python())
        else:
            converted.append(str(arg))

    # Simple % formatting — supports %s, %d, %x.
    result = fmt % tuple(converted)
    return result


# ---------------------------------------------------------------------------
# Stdout access
# ---------------------------------------------------------------------------

class StdoutFile:
    """Wrapper for stdout that supports writing and reading as a file object."""

    __slots__ = ("_fd",)

    def __init__(self, fd=None):
        self._fd = fd if fd is not None else 1  # sys.stdout.fileno()

    @property
    def fd(self) -> int:
        return self._fd

    def write(self, data: bytes):
        """Write raw bytes to stdout."""
        os.write(self._fd, data)

    def read_file(self, allocator):
        """Attempt to read from stdout — not supported.

        Returns None since stdout is typically a terminal/pipe (not readable).
        """
        return None


# ---------------------------------------------------------------------------
# Std module object — instantiated once at interpreter startup
# ---------------------------------------------------------------------------

class StdModule:
    """The std module providing built-in runtime services.

    This is the entry point for all runtime functionality available to
    NGPL programs. It is initialized once when the interpreter starts
    and its methods are registered as builtin functions in the global env.
    """

    def _sha256(self, data: bytes) -> int:
        """Compute SHA-256 hash of the given bytes.

        Args:
            data: The bytes to hash.

        Returns:
            An integer representing the 256-bit digest (H0<<224 | ... | H7).
        """
        h = hashlib.sha256(data).digest()
        result = int.from_bytes(h, 'big')
        return result

    def __init__(self):
        self._allocator = MmapAllocator()
        self._fs = None  # lazy-initialized fs object
        self._heap = None  # lazy-initialized heap submodule
        self._arena = None  # lazy-initialized arena submodule
        self._env = None  # lazy-initialized env submodule
        self._sys = None  # lazy-initialized sys submodule
        self._stdout_file = StdoutFile()
        self.args = ArgsModule()

    @property
    def fs(self):
        """Lazy-access to the fs directory opener."""
        if self._fs is None:
            self._fs = FsModule()
        return self._fs

    @property
    def heap(self):
        """Lazy-access to the heap allocator management."""
        if self._heap is None:
            self._heap = _HeapModuleStd(self)
        return self._heap

    @property
    def arena(self):
        """Lazy-access to the arena allocator submodule."""
        if self._arena is None:
            self._arena = _ArenaModuleStd()
        return self._arena

    @property
    def env(self):
        """Lazy-access to the process environment submodule."""
        if self._env is None:
            self._env = EnvModule()
        return self._env

    @property
    def sys(self):
        """Lazy-access to the system CPU/memory information submodule."""
        if self._sys is None:
            self._sys = SysModule()
        return self._sys

    def get_allocator(self):
        """Get a reference to the global allocator.

        Returns:
            The MmapAllocator instance used by this runtime.
        """
        return self._allocator

    # ------------------------------------------------------------------
    # Builtin functions accessible as std.<name>(args)
    # ------------------------------------------------------------------

    def format(self, args):
        """format(allocator, fmt_str, ...) — format a string.

        Uses C++ std::format-style replacement fields: {} for default
        formatting, {:spec} for explicit format specifiers.  Supported
        specifiers: d (decimal), x (hex), X (upper hex), b (binary),
        o (octal), c (character).

        Arrays and tuples are printed as [elem, elem, ...] with nested
        dimensions following the same pattern.

        Args:
            args[0]: allocator (accepted for API consistency, unused in
                     the interpreter since strings are Python objects).
            args[1]: StrValue — the format template.
            args[2:]: values to substitute into {} placeholders.

        Returns:
            StrValue with the formatted result.
        """
        from interp.eval import unwrap_optional
        from interp.value import (IntValue, FloatValue, BoolValue, StrValue, ObjectValue,
                                  ArrayValue, TupleValue, EnumValue,
                                  ExpectedValue, NoneValue, TypeValue,
                                  FuncValue, LambdaValue, UnitValue, mk_str)
        if len(args) < 2:
            raise TypeError("std.format(allocator, fmt_str, ...) requires at least 2 arguments")
        template_val = unwrap_optional(args[1])
        if not isinstance(template_val, StrValue):
            raise TypeError(
                f"std.format: format string must be str, got {type(template_val).__name__}")
        fmt = template_val.value
        fmt_args = args[2:]

        def _fmt_value(v, spec: str = "") -> str:
            uv = unwrap_optional(v)
            if isinstance(uv, UnitValue):
                return _fmt_value(uv.inner, spec) + " " + uv.unit.display_name
            if isinstance(uv, ExpectedValue):
                if uv.is_ok():
                    return _fmt_value(uv.ok_value, spec)
                return _fmt_value(uv.err_value, spec)
            if isinstance(uv, NoneValue):
                return "\N{EMPTY SET}"
            if isinstance(uv, BoolValue):
                return "true" if uv.value else "false"
            if isinstance(uv, StrValue):
                return uv.value
            if isinstance(uv, EnumValue):
                return uv.display()
            if isinstance(uv, TypeValue):
                return uv.name
            if isinstance(uv, IntValue):
                if spec == "x":
                    return format(uv.value, "x")
                if spec == "X":
                    return format(uv.value, "X")
                if spec == "b":
                    return format(uv.value, "b")
                if spec == "o":
                    return format(uv.value, "o")
                if spec == "c":
                    return chr(uv.value)
                return str(uv.value)
            if isinstance(uv, FloatValue):
                if spec:
                    return format(uv.value, spec)
                return repr(uv.value)
            if isinstance(uv, TupleValue):
                inner = ", ".join(_fmt_value(e) for e in uv.elements)
                return "[" + inner + "]"
            if isinstance(uv, ObjectValue):
                obj = uv.obj
                if isinstance(obj, ArrayValue):
                    inner = ", ".join(_fmt_value(e) for e in obj.elements)
                    return "[" + inner + "]"
                if isinstance(obj, Bytes):
                    return "[" + ", ".join(str(b) for b in obj.data) + "]"
                return f"<{type(obj).__name__}>"
            if isinstance(uv, (FuncValue, LambdaValue)):
                name = getattr(uv, "name", "\N{GREEK SMALL LETTER LAMDA}")
                return f"<fn {name}>"
            return str(uv)

        result: list[str] = []
        arg_idx = 0
        i = 0
        while i < len(fmt):
            ch = fmt[i]
            if ch == "{":
                if i + 1 < len(fmt) and fmt[i + 1] == "{":
                    result.append("{")
                    i += 2
                    continue
                end = fmt.index("}", i + 1)
                field = fmt[i + 1:end]
                spec = ""
                if ":" in field:
                    spec = field.split(":", 1)[1]
                if arg_idx >= len(fmt_args):
                    raise TypeError(
                        f"std.format: not enough arguments (need at least {arg_idx + 1}, "
                        f"got {len(fmt_args)})")
                result.append(_fmt_value(fmt_args[arg_idx], spec))
                arg_idx += 1
                i = end + 1
            elif ch == "}" and i + 1 < len(fmt) and fmt[i + 1] == "}":
                result.append("}")
                i += 2
            else:
                result.append(ch)
                i += 1

        return mk_str("".join(result))

    def get_stdout(self, args):
        """get_stdout() — get a file descriptor for the standard output.

        Args:
            args: argument list (unused).

        Returns:
            ObjectValue wrapping the StdoutFile instance.
        """
        if len(args) != 0:
            raise TypeError("get_stdout() takes no arguments")
        from interp.value import ObjectValue
        return ObjectValue(self._stdout_file)

    def sha256(self, args):
        """sha256(data) — compute SHA-256 hash as arbitrary-width integer.

        Args:
            args[0]: byte[] ArrayValue, Bytes, or StrValue object to hash.

        Returns:
            IntValue representing the 256-bit digest.
        """
        from interp.eval import unwrap_optional
        from interp.value import ObjectValue, StrValue, IntValue, ArrayValue, mk_int
        if len(args) != 1:
            raise TypeError("sha256(data) takes exactly 1 argument")
        data_arg = unwrap_optional(args[0])
        if isinstance(data_arg, ObjectValue):
            if isinstance(data_arg.obj, ArrayValue):
                data = bytes(e.value & 0xFF for e in data_arg.obj.elements
                             if isinstance(e, IntValue))
            elif isinstance(data_arg.obj, Bytes):
                data = bytes(data_arg.obj.data)
            else:
                raise TypeError(f"sha256 expects byte[] or StrValue, got {type(data_arg.obj).__name__}")
        elif isinstance(data_arg, StrValue):
            data = data_arg.value.encode("utf-8")
        else:
            raise TypeError(f"sha256 expects byte[] or StrValue, got {type(data_arg).__name__}")
        h = self._sha256(data)
        return mk_int(h)

    def bytes(self, args):
        """bytes(str) -- create a byte[] array from a UTF-8 string."""
        from interp.eval import unwrap_optional
        from interp.value import StrValue, ObjectValue, ArrayValue, mk_int
        if len(args) != 1:
            raise TypeError("bytes(str) takes exactly 1 argument")
        arg = unwrap_optional(args[0])
        if not isinstance(arg, StrValue):
            raise TypeError(f"bytes() expects string, got {type(arg).__name__}")
        raw = arg.value.encode("utf-8")
        elements = [mk_int(b, "byte") for b in raw]
        return ObjectValue(ArrayValue(elements, element_type="byte"))

    def print(self, args):
        """print(...) — format arguments and write to stdout.

        This is a convenience function that concatenates all argument values
        (like format) and writes the result followed by a newline to stdout.

        Args:
            args: list of NGPL Value objects.

        Returns:
            NoneValue.
        """
        from interp.eval import unwrap_optional
        from interp.value import (IntValue, FloatValue, BoolValue, StrValue, ObjectValue,
                                  ArrayValue, EnumValue, ExpectedValue, NoneValue,
                                  UnitValue, mk_str)

        parts = []
        for arg in args:
            uv = unwrap_optional(arg) if not isinstance(arg, ExpectedValue) else arg
            if isinstance(uv, UnitValue):
                parts.append(uv.display())
            elif isinstance(uv, ExpectedValue):
                parts.append(uv.display())
            elif isinstance(uv, EnumValue):
                parts.append(uv.display())
            elif isinstance(uv, IntValue):
                if uv.value.bit_length() > 32 or uv.value < 0:
                    parts.append(format(uv.value, "x"))
                else:
                    parts.append(str(uv.value))
            elif isinstance(uv, FloatValue):
                parts.append(repr(uv.value))
            elif isinstance(uv, BoolValue):
                parts.append("true" if uv.value else "false")
            elif isinstance(uv, StrValue):
                parts.append(uv.value)
            elif isinstance(uv, ObjectValue):
                obj = uv.obj
                if isinstance(obj, ArrayValue):
                    parts.append(f"<{obj.element_type or 'byte'}[{obj.sizeof}]>")
                elif isinstance(obj, int):
                    parts.append(str(obj))
                elif isinstance(obj, Bytes):
                    parts.append(f"<bytes {len(obj.data)}>")
                else:
                    parts.append(f"<{type(obj).__name__}>")
            elif isinstance(uv, NoneValue):
                parts.append(uv.display())
            else:
                parts.append(str(uv))

        output = "".join(parts) + "\n"
        os.write(1, output.encode("utf-8"))
        return mk_str("")

    # ------------------------------------------------------------------
    # SHA-256 helpers — byte-level ops and block compression.
    # These provide the mutable-byte operations that NGPL cannot yet
    # express without arrays or mutable state.  The message-schedule
    # expansion (W[16..79]) is implemented in NGPL using bitwise
    # operators (& | ^ ~ << >>) and recursion.
    # ------------------------------------------------------------------

    def sha256_pad(self, args):
        """sha256_pad(data_handle) — pad input per SHA-256 spec.

        Returns an ObjectValue wrapping the padded bytearray so NGPL code
        can extract bytes via sha256_getbyte and words via sha256_getword.
        """
        if len(args) != 1:
            raise TypeError("sha256_pad(handle) takes exactly 1 argument")

        data_arg = unwrap_optional(args[0])
        buf = None
        if isinstance(data_arg, Bytes):
            buf = bytearray(data_arg.data)
        elif isinstance(data_arg, ObjectValue) and hasattr(data_arg.obj, 'data'):
            buf = bytearray(data_arg.obj.data)
        else:
            raise TypeError("sha256_pad expects a Bytes object")

        length = len(buf)
        msg_bit_len = length * 8
        padding_len = (56 - ((length + 1) % 64)) % 64 + 8
        buf.append(0x80)
        buf.extend(b'\x00' * padding_len)
        buf += msg_bit_len.to_bytes(8, 'big')

        result = Bytes(buf)
        h = id(result)
        self._sha256_handle_data[h] = buf
        return ObjectValue(result)

    def sha256_getbyte(self, args):
        """sha256_getbyte(padded_handle, pos) — extract byte at offset.

        Returns an IntValue with value 0..255.
        """
        if len(args) != 2:
            raise TypeError("sha256_getbyte(handle, pos)")
        handle_arg = unwrap_optional(args[0])
        if not isinstance(handle_arg, IntValue):
            raise TypeError("pos must be int")

        pos = int(handle_arg.value)
        buf = None
        if isinstance(pos < 0 or pos >= 8):
            return mk_int(0)

        # First arg (args[0]) is the Bytes/ByteArray handle.
        data_arg = unwrap_optional(args[0])
        if isinstance(data_arg, Bytes):
            buf = bytes(data_arg.data)
        elif isinstance(data_arg, bytearray):
            buf = bytes(data_arg)
        elif isinstance(data_arg, int):
            buf = bytes(self._sha256_handle_data.get(data_arg, b''))

        pos = int(unwrap_optional(args[1]).value)
        if buf is None or pos >= len(buf):
            return mk_int(0)
        return mk_int(buf[pos])

    def sha256_getword(self, args):
        """sha256_getword(handle, byte_offset) — extract 32-bit big-endian word.

        Returns an IntValue.
        """
        if len(args) != 2:
            raise TypeError("sha256_getword(handle, off)")

        data_arg = unwrap_optional(args[0])
        buf = None
        if isinstance(data_arg, Bytes):
            buf = bytes(data_arg.data)
        elif isinstance(data_arg, bytearray):
            buf = bytes(data_arg)
        elif isinstance(data_arg, int):
            buf = bytes(self._sha256_handle_data.get(data_arg, b''))

        if buf is None:
            return mk_int(0)

        off = int(unwrap_optional(args[1]).value)
        if off + 4 > len(buf):
            return mk_int(0)
        w = (buf[off] << 24) | (buf[off+1] << 16) | (buf[off+2] << 8) | buf[off+3]
        return mk_int(w & 0xffffffff)

    def sha256_compress(self, args):
        """sha256_compress(padded_handle, offset, h0..h7) — compress one block.

        Returns an IntValue with the updated 256-bit hash state packed as:
          result = (a<<224)|(b<<192)|(c<<160)|(d<<128)|(e<<96)|(f<<64)|(g<<32)|h
        """
        if len(args) != 9:
            raise TypeError("sha256_compress(handle, offset, h0..h7)")

        buf = None
        data_arg = unwrap_optional(args[0])
        if isinstance(data_arg, Bytes):
            buf = bytes(data_arg.data)
        elif isinstance(data_arg, bytearray):
            buf = bytes(data_arg)
        elif isinstance(data_arg, int):
            buf = bytes(self._sha256_handle_data.get(data_arg, b''))

        offset = int(unwrap_optional(args[1]).value)
        if buf is None or offset + 64 > len(buf):
            # Return unchanged hash state.
            h0 = int(unwrap_optional(args[2]).value) & 0xffffffff
            h1 = int(unwrap_optional(args[3]).value) & 0xffffffff
            h2 = int(unwrap_optional(args[4]).value) & 0xffffffff
            h3 = int(unwrap_optional(args[5]).value) & 0xffffffff
            h4 = int(unwrap_optional(args[6]).value) & 0xffffffff
            h5 = int(unwrap_optional(args[7]).value) & 0xffffffff
            h6 = int(unwrap_optional(args[8]).value) & 0xffffffff
            result = (h0 << 224 | h1 << 192 | h2 << 160 | h3 << 128 |
                      h4 << 96 | h5 << 64 | h6 << 32)
            return mk_int(result & ((1 << 256) - 1))

        # Standard SHA-256 block compression (FIPS 180-4 §4.2.2).
        w = [0] * 80
        for i in range(16):
            idx = offset + i * 4
            if idx + 4 <= len(buf):
                w[i] = (buf[idx] << 24) | (buf[idx+1] << 16) | (buf[idx+2] << 8) | buf[idx+3]

        for i in range(16, 80):
            s0 = ((w[i-15] >> 7) | (w[i-15] << 25)) & 0xffffffff
            s1 = ((w[i-2] >> 17) | (w[i-2] << 15)) & 0xffffffff
            w[i] = (w[i-16] + s0 + w[i-7] + s1) & 0xffffffff

        h_vals = [int(unwrap_optional(args[i]).value) & 0xffffffff for i in range(2, 9)]
        a, b, c, d, e, f, g, hh = h_vals

        K = [
            0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
            0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
            0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
            0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
            0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
            0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
            0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
            0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
            0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
            0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
            0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
            0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
            0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
            0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
            0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
        ]

        for t in range(64):
            S1 = (((e >> 6) | (e << 26)) ^ ((e >> 11) | (e << 21)) ^ ((e >> 25) | (e << 7))) & 0xffffffff
            ch_val = (e & f) ^ ((~e & 0xffffffff) & g)
            t1 = (hh + S1 + ch_val + K[t] + w[t]) & 0xffffffff
            S0 = (((a >> 2) | (a << 30)) ^ ((a >> 13) | (a << 19)) ^ ((a >> 22) | (a << 10))) & 0xffffffff
            maj_val = (a & b) ^ (a & c) ^ (b & c)
            t2 = (S0 + maj_val) & 0xffffffff
            a_new = (t1 + t2) & 0xffffffff
            b_new = a; c_new = b; d_new = c
            e_new = (d + t1) & 0xffffffff; f_new = e; g_new = f; hh = g
            a, b, c, d, e, f, g, hh = a_new, b_new, c_new, d_new, e_new, f_new, g_new, hh

        result = (((h_vals[0] + a) & 0xffffffff) << 224 |
                  ((h_vals[1] + b) & 0xffffffff) << 192 |
                  ((h_vals[2] + c) & 0xffffffff) << 160 |
                  ((h_vals[3] + d) & 0xffffffff) << 128 |
                  ((h_vals[4] + e) & 0xffffffff) << 96 |
                  ((h_vals[5] + f) & 0xffffffff) << 64 |
                  ((h_vals[6] + g) & 0xffffffff) << 32 |
                  (h_vals[7] + hh) & 0xffffffff)
        return mk_int(result & ((1 << 256) - 1))

    def pack_message_schedule(self, args):
        """Pack the 80-word message schedule for one SHA-256 block into a single large integer.

        Reads 16 words from the padded buffer at the given offset, computes all 80 W values
        using the standard FIPS 180-4 expansion formula, and packs them into a Python int
        where each word occupies 32 consecutive bit positions [i*32 .. (i+1)*32 - 1].

        This enables NGPL code to express the full message-schedule computation using
        only bitwise shift-and-mask operations — no arrays or mutable state required.

        Args:
            args[0]: IntValue — byte offset into padded data.
            args[1]: ObjectValue wrapping a Bytes object (the padded buffer).

        Returns:
            IntValue — packed 2560-bit integer holding all 80 W values.
        """
        if len(args) != 2:
            raise TypeError("pack_message_schedule(offset, handle)")

        offset = int(unwrap_optional(args[0]).value)
        data_arg = unwrap_optional(args[1])
        buf = None
        if isinstance(data_arg, Bytes):
            buf = bytes(data_arg.data)
        elif isinstance(data_arg, bytearray):
            buf = bytes(data_arg)
        else:
            raise TypeError("handle must be a Bytes object")

        if offset + 64 > len(buf):
            return mk_int(0)

        # Read the initial 16 words from the block.
        w = [0] * 80
        for i in range(16):
            idx = offset + i * 4
            w[i] = (buf[idx] << 24) | (buf[idx + 1] << 16) | (buf[idx + 2] << 8) | buf[idx + 3]

        # Compute W[16..79] using FIPS 180-4 §4.2.2 expansion.
        for i in range(16, 80):
            s0 = ((w[i - 15] >> 7) | (w[i - 15] << 25)) & 0xffffffff
            s1 = ((w[i - 2] >> 17) | (w[i - 2] << 15)) & 0xffffffff
            w[i] = (w[i - 16] + s0 + w[i - 7] + s1) & 0xffffffff

        # Pack all 80 words into one integer: word i occupies bits [i*32 .. (i+1)*32 - 1].
        packed = 0
        for i in range(80):
            packed |= w[i] << (i * 32)

        return mk_int(packed)


class ArenaAllocator:
    """Arena allocator backed by mmap().

    Allocates from a bump pointer within mmap regions.  Individual
    allocations cannot be freed; deinit() releases all regions at once.
    Each call to std.arena.allocator() creates a fresh, independent arena.
    """

    __slots__ = ("_regions", "_offset", "_capacity", "_alive")

    def __init__(self):
        self._regions: list[mmap.mmap] = []
        self._offset = 0
        self._capacity = 0
        self._alive = True

    def _grow(self, min_size: int):
        size = max(4 * 1024 * 1024, ((min_size + 4095) // 4096) * 4096)
        try:
            region = mmap.mmap(-1, size, mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
                               MmapAllocator.PROT_READ | MmapAllocator.PROT_WRITE)
        except OSError as e:
            raise MemoryError(f"arena mmap failed: {e}")
        self._regions.append(region)
        self._offset = 0
        self._capacity = size

    def alloc(self, size: int):
        if not self._alive:
            raise MemoryError("arena has been deinitialized")
        if size <= 0:
            return Bytes(bytearray(0))
        if self._offset + size > self._capacity:
            self._grow(size)
        buf = bytearray(size)
        region = self._regions[-1]
        region[self._offset:self._offset + size] = buf
        self._offset += size
        return Bytes(buf)

    def reset(self):
        for region in self._regions:
            region.close()
        self._regions.clear()
        self._offset = 0
        self._capacity = 0

    def deinit(self):
        self.reset()
        self._alive = False


class _HeapModuleStd:
    """The heap submodule — provides allocator access via std.heap.allocator()."""

    def __init__(self, parent):
        self._parent = parent

    def allocator(self):
        """Get the global mmap-backed allocator."""
        return self._parent._allocator


class _ArenaModuleStd:
    """The arena submodule — provides arena allocator creation via std.arena.allocator()."""

    def allocator(self):
        """Create and return a new arena allocator."""
        return ArenaAllocator()


def _count(n: int):
    """Wrap a plain integer as a value carrying the abstract `count` unit."""
    from interp.units import BUILTIN_UNITS
    from interp.value import UnitValue, mk_int
    return UnitValue(mk_int(n), BUILTIN_UNITS["count"])


def _bytes_of(n: int):
    """Wrap a plain integer as a value carrying the `byte` unit."""
    from interp.units import BUILTIN_UNITS
    from interp.value import UnitValue, mk_int
    return UnitValue(mk_int(n), BUILTIN_UNITS["byte"])


def _str_array(items):
    """Build a `str[]` array value from an iterable of Python strings."""
    from interp.value import ArrayValue, ObjectValue, mk_str
    return ObjectValue(ArrayValue([mk_str(s) for s in items], element_type="str"))


def _int_array(items):
    """Build an `int[]` array value from an iterable of Python integers."""
    from interp.value import ArrayValue, ObjectValue, mk_int
    return ObjectValue(ArrayValue([mk_int(i) for i in items], element_type="int"))


def _as_index(value, what: str) -> int:
    """Coerce a language-level index argument to a Python integer.

    Accepts a bare Python int (already unwrapped by the method-call
    machinery) as well as IntValue and unit-bearing integers, so that a
    loop variable carrying `count` or `ptrdiff` can be used directly.
    """
    from interp.value import IntValue, UnitValue
    if isinstance(value, UnitValue):
        value = value.inner
    if isinstance(value, IntValue):
        return value.value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise TypeError(f"{what}: index must be an integer")


def _as_name(value, what: str) -> str:
    """Coerce a language-level string argument to a Python string."""
    from interp.value import StrValue
    if isinstance(value, StrValue):
        return value.value
    if isinstance(value, str):
        return value
    raise TypeError(f"{what}: name must be a str")


class ArgsModule:
    """The args submodule providing the program's command line parameters.

    The interpreter fills this in at startup: `program` is the source
    file being run and `params` are the arguments that follow the `--`
    separator on the interpreter command line.  A compiled program will
    instead take both directly from the initial process stack.
    """

    __slots__ = ("_program", "_params")

    def __init__(self):
        self._program = ""
        self._params: list[str] = []

    def set_command_line(self, program: str, params: list[str]):
        """Install the program name and parameter list (interpreter startup)."""
        self._program = program
        self._params = list(params)

    def program(self):
        """The name the program was invoked as."""
        from interp.value import mk_str
        return mk_str(self._program)

    def count(self):
        """The number of parameters, excluding the program name."""
        return _count(len(self._params))

    def get(self, index):
        """Return the parameter at the given zero-based index."""
        i = _as_index(index, "std.args.get")
        if not 0 <= i < len(self._params):
            raise IndexError(
                f"std.args.get: index {i} out of range "
                f"(count {len(self._params)})")
        from interp.value import mk_str
        return mk_str(self._params[i])

    def all(self):
        """Return all parameters as a `str[]`, excluding the program name."""
        return _str_array(self._params)


class EnvModule:
    """The env submodule providing read access to the process environment.

    Values are read from the libc `environ` array on every call rather
    than cached, so a variable changed by a lower layer is observed.
    The environment is read-only from the language: there is no setter.
    """

    def get(self, name):
        """Look up a variable; returns the value or ∅ when it is unset."""
        from interp.value import mk_str, none
        key = _as_name(name, "std.env.get")
        raw = _getenv(key.encode("utf-8"))
        if raw is None:
            return none()
        return mk_str(_decode(raw))

    def has(self, name):
        """Report whether a variable is present in the environment."""
        from interp.value import mk_bool
        key = _as_name(name, "std.env.has")
        return mk_bool(_getenv(key.encode("utf-8")) is not None)

    def count(self):
        """The number of variables in the environment."""
        return _count(len(_environ_entries()))

    def names(self):
        """Return the names of all environment variables as a `str[]`."""
        return _str_array(e.partition("=")[0] for e in _environ_entries())


class SysModule:
    """The sys submodule exposing CPU and memory properties of the system.

    The affinity mask is the authoritative answer to "how many CPUs may
    this program use": it accounts for cpusets and taskset restrictions
    that the raw CPU count does not.
    """

    def affinity(self):
        """The CPU affinity mask, with bit *n* set when CPU *n* is usable."""
        from interp.value import mk_int
        return mk_int(_affinity_mask())

    def affinity_cpus(self):
        """The ids of the CPUs in the affinity mask, ascending, as `int[]`."""
        mask = _affinity_mask()
        cpus = []
        cpu = 0
        while mask:
            if mask & 1:
                cpus.append(cpu)
            mask >>= 1
            cpu += 1
        return _int_array(cpus)

    def usable_cpus(self):
        """The number of CPUs this program may run on (popcount of the mask)."""
        return _count(_affinity_mask().bit_count())

    def total_cpus(self):
        """The number of CPUs configured on the system, usable or not."""
        return _count(_checked_sysconf(_SC_NPROCESSORS_CONF, "_SC_NPROCESSORS_CONF"))

    def online_cpus(self):
        """The number of CPUs currently online."""
        return _count(_checked_sysconf(_SC_NPROCESSORS_ONLN, "_SC_NPROCESSORS_ONLN"))

    def page_size(self):
        """The size of a memory page."""
        return _bytes_of(_checked_sysconf(_SC_PAGESIZE, "_SC_PAGESIZE"))

    def total_memory(self):
        """The total amount of physical memory installed in the system."""
        pages = _checked_sysconf(_SC_PHYS_PAGES, "_SC_PHYS_PAGES")
        return _bytes_of(pages * _checked_sysconf(_SC_PAGESIZE, "_SC_PAGESIZE"))


class FsModule:
    """The fs submodule providing filesystem operations via AT_FDCWD."""

    def cwd(self):
        """Open and return a DirFD for the current working directory."""
        try:
            fd = _openat(AT_FDCWD, b".", O_RDONLY | O_DIRECTORY)
        except Exception as e:
            raise OSError(f"failed to open current directory: {e}")
        if fd < 0:
            errno = ctypes.get_errno()
            raise OSError(f"openat(., O_DIRECTORY): {os.strerror(errno)} (errno={errno})")
        return DirFD(fd)


# ---------------------------------------------------------------------------
# Global std instance — available at interpreter startup
# ---------------------------------------------------------------------------

std = StdModule()
