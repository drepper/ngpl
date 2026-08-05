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
        from interp.value import IntValue, BoolValue, StrValue, ObjectValue, ArrayValue, EnumValue, mk_str

        parts = []
        for arg in args:
            uv = unwrap_optional(arg)
            if isinstance(uv, EnumValue):
                parts.append(uv.display())
            elif isinstance(uv, IntValue):
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
                if isinstance(obj, ArrayValue):
                    parts.append(f"<byte[{obj.sizeof}]>")
                elif isinstance(obj, Bytes):
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
            args: list of newlang Value objects.

        Returns:
            NoneValue.
        """
        from interp.eval import unwrap_optional
        from interp.value import IntValue, BoolValue, StrValue, ObjectValue, ArrayValue, EnumValue, mk_str

        parts = []
        for arg in args:
            uv = unwrap_optional(arg)
            if isinstance(uv, EnumValue):
                parts.append(uv.display())
            elif isinstance(uv, IntValue):
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
                if isinstance(obj, ArrayValue):
                    parts.append(f"<byte[{obj.sizeof}]>")
                elif isinstance(obj, int):
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

    # ------------------------------------------------------------------
    # SHA-256 helpers — byte-level ops and block compression.
    # These provide the mutable-byte operations that newlang cannot yet
    # express without arrays or mutable state.  The message-schedule
    # expansion (W[16..79]) is implemented in newlang using bitwise
    # operators (& | ^ ~ << >>) and recursion.
    # ------------------------------------------------------------------

    def sha256_pad(self, args):
        """sha256_pad(data_handle) — pad input per SHA-256 spec.

        Returns an ObjectValue wrapping the padded bytearray so newlang code
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

        This enables newlang code to express the full message-schedule computation using
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


class _HeapModuleStd:
    """The heap submodule — provides allocator access via std.heap.allocator()."""

    def __init__(self, parent):
        self._parent = parent

    def allocator(self):
        """Get the global mmap-backed allocator."""
        return self._parent._allocator


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
