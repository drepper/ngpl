"""Standard library (std) runtime.

Implements the built-in modules available to all newlang programs.
Uses direct system calls via ctypes where Python's os module does not
expose sufficient low-level control.

The std object exposes:
    fs.cwd()          → DirFD wrapper (opens current dir with O_DIRECTORY)
    heap              → Allocator management (mmap-backed)
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
            4. Return Bytes(buffer) — caller converts to StrValue as needed.

        Args:
            allocator: an MmapAllocator instance.

        Returns:
            A Bytes object containing the file's raw content.
        """
        fsize = _get_file_size(self._fd)
        buf_result = allocator.alloc(fsize)

        if buf_result is None or buf_result.data is None:
            raise MemoryError("allocation failed in read_file")

        # Read all bytes at once (fine for this prototype; files are small).
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
                break  # short read — end of file
            buf_result.data[pos:pos + len(n)] = n
            pos += len(n)
            total_read += len(n)

        # Truncate buffer to actual data read.
        buf_result.data = buf_result.data[:total_read]
        return buf_result

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
# SHA-256
# ---------------------------------------------------------------------------

def _sha256(data: bytes) -> int:
    """Compute SHA-256 hash of data, returning the result as an arbitrary-width integer.

    Args:
        data: raw bytes to hash.

    Returns:
        The 256-bit hash value as a Python int (arbitrary precision).
    """
    h = hashlib.sha256(data)
    digest = h.digest()  # 32 bytes
    # Convert big-endian bytes to int.
    result = 0
    for byte in digest:
        result = (result << 8) | byte
    return result


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format_string(template, *args):
    """Format a string with optional arguments.

    Supports %s (string), %d (int), %x (hex), %X (uppercase hex).
    The template is a newlang StrValue; args are runtime Values.

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
    newlang programs. It is initialized once when the interpreter starts
    and its methods are registered as builtin functions in the global env.
    """

    def __init__(self):
        self._allocator = MmapAllocator()
        self._fs = None  # lazy-initialized fs object
        self._heap = None  # lazy-initialized heap submodule
        self._stdout_file = StdoutFile()

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

    def get_allocator(self):
        """Get a reference to the global allocator.

        Returns:
            The MmapAllocator instance used by this runtime.
        """
        return self._allocator

    # ------------------------------------------------------------------
    # Builtin functions accessible as std.<name>(args)
    # ------------------------------------------------------------------

    def sha256(self, args):
        """sha256(data) — compute SHA-256 hash of data.

        Args:
            args: list of newlang Value objects (already evaluated).

        Returns:
            IntValue containing the 256-bit hash as an arbitrary-width integer.
        """
        if len(args) != 1:
            raise TypeError("sha256(data) takes exactly 1 argument")
        from interp.eval import unwrap_optional
        from interp.value import StrValue, ObjectValue

        data_arg = unwrap_optional(args[0])
        if isinstance(data_arg, ObjectValue):
            obj = data_arg.obj
            if isinstance(obj, Bytes):  # Bytes class is defined above in this file
                data = bytes(obj.data)
            else:
                raise TypeError(
                    f"sha256 expects Bytes or StrValue, got {type(obj).__name__}")
        elif isinstance(data_arg, StrValue):
            data = data_arg.value.encode("utf-8")
        else:
            raise TypeError(
                f"sha256 expects Bytes or StrValue, got {type(data_arg).__name__}")
        h = _sha256(data)
        from interp.value import mk_int
        return mk_int(h)

    def format(self, args):
        """format(str, ...) — format a string.

        Concatenates all argument values into a single string and returns it.
        This is the pure formatting function; side-effect operations like
        printing to stdout are handled by the caller using ``std.get_stdout().fd``
        with an appropriate write call.

        Args:
            args: list of newlang Value objects — each is converted to a string
                  and concatenated.

        Returns:
            StrValue with the concatenated result (no trailing newline).
        """
        from interp.eval import unwrap_optional
        from interp.value import IntValue, BoolValue, StrValue, ObjectValue, mk_str

        parts = []
        for arg in args:
            uv = unwrap_optional(arg)
            if isinstance(uv, IntValue):
                # Large integers (e.g. hashes) formatted as hex; small ones decimal.
                if uv.value.bit_length() > 32 or uv.value < 0:
                    parts.append(format(uv.value, "x"))
                else:
                    parts.append(str(uv.value))
            elif isinstance(uv, BoolValue):
                parts.append("true" if uv.value else "false")
            elif isinstance(uv, StrValue):
                parts.append(uv.value)
            elif isinstance(uv, ObjectValue):
                obj = uv.obj
                if isinstance(obj, Bytes):
                    parts.append(f"<bytes {len(obj.data)}>")
                elif isinstance(obj, int):
                    parts.append(format(obj, "x") if obj.bit_length() > 32 else str(obj))
                else:
                    parts.append(f"<{type(obj).__name__}>")
            else:
                parts.append(str(uv))

        return mk_str("".join(parts))

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

    def print(self, args):
        """print(...) — format arguments and write to stdout.

        This is a convenience function that concatenates all argument values
        (like format) and writes the result followed by a newline to stdout.

        Args:
            args: list of newlang Value objects.

        Returns:
            NoneValue.
        """
        from interp.eval import unwrap_optional
        from interp.value import IntValue, BoolValue, StrValue, ObjectValue, mk_str

        parts = []
        for arg in args:
            uv = unwrap_optional(arg)
            if isinstance(uv, IntValue):
                if uv.value.bit_length() > 32 or uv.value < 0:
                    parts.append(format(uv.value, "x"))
                else:
                    parts.append(str(uv.value))
            elif isinstance(uv, BoolValue):
                parts.append("true" if uv.value else "false")
            elif isinstance(uv, StrValue):
                parts.append(uv.value)
            elif isinstance(uv, ObjectValue):
                obj = uv.obj
                if isinstance(obj, int):
                    parts.append(str(obj))
                elif isinstance(obj, Bytes):
                    parts.append(f"<bytes {len(obj.data)}>")
                else:
                    parts.append(f"<{type(obj).__name__}>")
            else:
                parts.append(str(uv))

        output = "".join(parts) + "\n"
        os.write(1, output.encode("utf-8"))
        return mk_str("")


class _HeapModuleStd:
    """The heap submodule — provides allocator access via std.heap.allocator()."""

    def __init__(self, parent):
        self._parent = parent

    def allocator(self):
        """Get the global mmap-backed allocator.

        Returns:
            The MmapAllocator instance used by this runtime.
        """
        return self._parent._allocator


class FsModule:
    """The fs submodule providing filesystem operations via AT_FDCWD.

    All operations use explicit file descriptors — no bare path resolution
    that bypasses the kernel's directory-based interface model.
    """

    def cwd(self):
        """Open and return a DirFD for the current working directory.

        Uses openat(AT_FDCWD, ".", O_RDONLY | O_DIRECTORY) to obtain a
        directory file descriptor tied to the process's cwd.

        Returns:
            A DirFD instance wrapping the opened directory fd.
        """
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
