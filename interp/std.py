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
    hash              → digests: hash.sha256.digest(x), hash.sha256.start()
    format(str, file?, fd?) → Format a string, optionally write to a file descriptor
    get_stdout()      → StdoutFile object wrapping stdout fd

All filesystem operations use AT_FDCWD or explicit dirfd — no bare path
operations that would bypass the kernel's directory-based interfaces.
"""

import ctypes
import ctypes.util
import hashlib
import struct
import math as _math
import mmap

from interp.errors import coded
import os
import sys


# ---------------------------------------------------------------------------
# Constants (Linux x86_64)
# ---------------------------------------------------------------------------

libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
AT_FDCWD = -100  # current working directory for openat
O_RDONLY = 0
O_WRONLY = 0o1
O_CREAT = 0o100
O_TRUNC = 0o1000
O_DIRECTORY = 0o200000  # must be a directory
O_CLOEXEC = 0o2000000
S_IRUSR = 0o400       # user read
S_IWUSR = 0o200       # user write
EINVAL = 22           # invalid argument
SYS_GETDENTS64 = 217  # x86_64 syscall number

# File type bits from <sys/stat.h>.  getdents64 reports a directory
# entry's type as a DT_* value, which is the corresponding S_IF* value
# shifted right by 12, so one table serves for both.
S_IFMT_SHIFT = 12
_FILE_TYPES: dict[str, int] = {
    "unknown": 0,          # DT_UNKNOWN: the filesystem did not say
    "fifo": 0o010000,      # S_IFIFO
    "chr": 0o020000,       # S_IFCHR
    "dir": 0o040000,       # S_IFDIR
    "blk": 0o060000,       # S_IFBLK
    "reg": 0o100000,       # S_IFREG
    "lnk": 0o120000,       # S_IFLNK
    "sock": 0o140000,      # S_IFSOCK
}

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


def resolve_abort_signal(signal_number: int) -> int:
    """Pick the signal std.abort will raise.

    Args:
        signal_number: the requested signal, or 0 for none.

    Returns:
        The requested signal when it is one the system defines, and
        SIGABRT otherwise.
    """
    import signal as _signal

    if signal_number and signal_number in {s.value for s in _signal.valid_signals()
                                           if hasattr(s, "value")}:
        return signal_number
    return _signal.SIGABRT


def deliver_abort(signal_number: int):
    """Terminate the current process with the given signal.

    The handler is reset to the default first so that the process really
    is killed by the signal and the parent sees it in the wait status,
    rather than the signal being caught and ignored.
    """
    import signal as _signal

    try:
        _signal.signal(signal_number, _signal.SIG_DFL)
    except (OSError, ValueError):
        pass  # SIGKILL and SIGSTOP cannot be reset, and need no reset
    sys.stdout.flush()
    sys.stderr.flush()
    os.kill(os.getpid(), signal_number)
    # A signal whose default action is to stop rather than terminate
    # returns here once the process is continued; leave in its stead.
    os._exit(128 + signal_number)


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

def make_file_type_enum():
    """Create the std.filetype enum naming the S_IF* file kinds."""
    from interp.value import EnumType
    return EnumType("filetype", "u32", dict(_FILE_TYPES), is_flag=False)


class DirEntry:
    """One entry of a directory, as reported by getdents64.

    name is the entry's name within its directory, never a path.  type
    is a std.filetype value; it is `unknown` when the filesystem does
    not record the kind in the directory itself, in which case the entry
    has to be opened to find out.
    """

    __slots__ = ("name", "type")

    def __init__(self, name: str, file_type):
        self.name = name
        self.type = file_type

    def display(self) -> str:
        return f"{self.name} ({self.type.display()})"


class DirIterator:
    """Walks a directory's entries using getdents64.

    Entries arrive from the kernel in blocks, so a buffer is refilled as
    it empties rather than the whole directory being read up front: a
    directory can be far larger than the program wants to hold.

    `.` and `..` are not produced.  Every caller that walks a tree would
    otherwise have to filter them, and one that forgets recurses for
    ever.
    """

    __slots__ = ("_fd", "_buffer", "_offset", "_length", "_done", "_types")

    _BUFFER_SIZE = 32768

    def __init__(self, fd: int, file_type_enum):
        self._fd = fd
        self._buffer = ctypes.create_string_buffer(self._BUFFER_SIZE)
        self._offset = 0
        self._length = 0
        self._done = False
        self._types = file_type_enum

    def _refill(self) -> bool:
        """Read the next block of entries; False when the directory ends."""
        if self._done:
            return False
        n = _getdents64(SYS_GETDENTS64, self._fd,
                        ctypes.cast(self._buffer, ctypes.c_void_p),
                        self._BUFFER_SIZE)
        if n < 0:
            errno = ctypes.get_errno()
            raise OSError(f"getdents64: {os.strerror(errno)} (errno={errno})")
        if n == 0:
            self._done = True
            return False
        self._offset = 0
        self._length = n
        return True

    def next(self):
        """Return the next entry, or ∅ when the directory is exhausted."""
        from interp.value import EnumValue, ObjectValue, none, some

        while True:
            if self._offset >= self._length:
                if not self._refill():
                    return none()
                continue

            raw = self._buffer.raw
            base = self._offset
            reclen = int.from_bytes(raw[base + 16:base + 18], "little")
            if reclen <= 0:
                # A malformed record would otherwise loop for ever.
                self._done = True
                return none()
            d_type = raw[base + 18]
            name_bytes = raw[base + 19:base + reclen]
            name = _decode(name_bytes.split(b"\x00", 1)[0])
            self._offset += reclen

            if name in (".", ".."):
                continue

            mode = d_type << S_IFMT_SHIFT
            for member, value in _FILE_TYPES.items():
                if value == mode:
                    file_type = EnumValue(self._types,
                                          self._types.members[member])
                    break
            else:
                file_type = EnumValue(self._types,
                                      self._types.members["unknown"])
            return some(ObjectValue(DirEntry(name, file_type)))

    def display(self) -> str:
        return "<directory iterator>"


class DirFD:
    """Wrapper around a file descriptor opened as a directory.

    Provides open_file() which calls openat(dirfd, pathname, flags).
    The raw fd is accessible via .fd for direct use in the language.

    Like FileStream, the descriptor is a resource owned by the binding
    the directory was assigned to, and is released when that binding's
    scope ends.  Without that, a function that opens a directory to reach
    one file would leak a descriptor on every call.
    """

    __slots__ = ("_fd", "_closed")

    def __init__(self, fd: int):
        self._fd = fd
        self._closed = False

    def _check_open(self, what: str):
        """Reject an operation on a directory that has already been closed."""
        if self._closed:
            raise coded(2269, OSError(f"{what}: directory is closed"))

    @property
    def is_closed(self) -> bool:
        """Whether the descriptor has been released."""
        return self._closed

    @property
    def fd(self) -> int:
        """The underlying directory file descriptor number."""
        self._check_open("fd")
        return self._fd

    def close(self):
        """Close the directory descriptor and make it unavailable."""
        self._check_open("close")
        _close(self._fd)
        self._closed = True

    def destroy(self):
        """Release the descriptor because the owning scope has ended."""
        if not self._closed:
            _close(self._fd)
            self._closed = True

    def iterate(self):
        """Return an iterator over this directory's entries.

        The iterator reads through this directory's descriptor, so it
        stops working once the directory is closed or its scope ends.
        """
        self._check_open("iterate")
        return DirIterator(self._fd, std.filetype)

    def open_file(self, name, mode=None, flags=None):
        """Open a file relative to this directory using openat.

        Args:
            name: filename (str or bytes).
            mode: POSIX mode bits (default 0o644).
            flags: openat flags (default O_RDONLY | O_CLOEXEC).

        Returns:
            An optional: ⊨(FileStream) when the file opened, ∅ when it
            could not be -- a file that is not there being an ordinary
            answer, not a failure of the program.  The caller decides
            what its absence means and says so in its own words.
        """
        from interp.value import ObjectValue, some, none

        self._check_open("open_file")
        if isinstance(name, str):
            name = name.encode("utf-8")
        if mode is None:
            mode = S_IRUSR | S_IWUSR
        if flags is None:
            flags = O_RDONLY | O_CLOEXEC
        fd = _openat(self._fd, name, flags)
        if fd < 0:
            return none()
        return some(ObjectValue(FileStream(fd)))

    def create_file(self, name, mode=None):
        """Create (or truncate) a file relative to this directory, for writing.

        Args:
            name: filename (str or bytes).
            mode: POSIX permission bits for a newly created file
                  (default 0o644).  Pass 0o755 for an executable.

        Returns:
            FileStream wrapping the new descriptor, open for writing.
        """
        self._check_open("create_file")
        if isinstance(name, str):
            name = name.encode("utf-8")
        if mode is None:
            mode = 0o644
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC,
                     mode, dir_fd=self._fd)
        # A creating open honors the umask; the program named the mode
        # it wants, so it is applied rather than filtered.
        os.fchmod(fd, mode)
        return FileStream(fd)

    def create_dir(self, name, mode=None):
        """Create a directory relative to this one; one already there is fine.

        Args:
            name: directory name (str or bytes).
            mode: POSIX permission bits (default 0o755).

        Returns:
            DirFD for the (possibly pre-existing) directory.
        """
        self._check_open("create_dir")
        if isinstance(name, str):
            name = name.encode("utf-8")
        if mode is None:
            mode = 0o755
        try:
            os.mkdir(name, mode, dir_fd=self._fd)
        except FileExistsError:
            pass
        return self.open_dir(name)

    def open_dir(self, name):
        """Open a directory relative to this one.

        Args:
            name: directory name (str or bytes).

        Returns:
            DirFD wrapping the new directory descriptor.
        """
        self._check_open("open_dir")
        if isinstance(name, str):
            name = name.encode("utf-8")
        fd = _openat(self._fd, name, O_RDONLY | O_DIRECTORY | O_CLOEXEC)
        if fd < 0:
            errno = ctypes.get_errno()
            raise OSError(f"openat({self._fd}, {name!r}): {os.strerror(errno)} (errno={errno})")
        return DirFD(fd)


# ---------------------------------------------------------------------------
# File stream wrapper
# ---------------------------------------------------------------------------

class IoVec:
    """One run of bytes waiting to be written.

    `std.iov` settles what a value's bytes are; this holds them, so a
    program can put a run in an array, count the array, and hand the
    whole of it to `writev` as one call.  It is opaque on purpose: a
    run is a thing to write, not a thing to read back or take apart.
    """

    __slots__ = ("data",)

    def __init__(self, data: bytes):
        self.data = data

    def display(self) -> str:
        return f"<std.iovec {len(self.data)} bytes>"


class FileStream:
    """Wrapper around an opened file descriptor.

    Provides read_file() which reads the entire file content into
    allocated memory using the provided allocator, then returns the
    result as a Bytes object containing the raw data.

    The file descriptor is a resource owned by the binding the stream was
    assigned to.  It is released when close() is called explicitly, and
    otherwise when that binding's scope ends.  Either way the stream
    becomes unavailable: every operation on a closed file is an error, so
    a descriptor cannot be used after it has been handed back to the
    kernel and possibly reissued to something else.
    """

    __slots__ = ("_fd", "_closed")

    def __init__(self, fd: int):
        self._fd = fd
        self._closed = False

    def _check_open(self, what: str):
        """Reject an operation on a file that has already been closed."""
        if self._closed:
            raise coded(2270, OSError(f"{what}: file is closed"))

    @property
    def is_closed(self) -> bool:
        """Whether the descriptor has been released."""
        return self._closed

    @property
    def fd(self) -> int:
        self._check_open("fd")
        return self._fd

    def device(self):
        """The device this file is on, as the system numbers it.

        Two names answer for one file exactly when the device and the
        number on it both agree; no name settles it, since a file has
        as many names as something cares to give it.
        """
        from interp.value import mk_int

        self._check_open("device")
        return mk_int(os.fstat(self._fd).st_dev, "i64")

    def inode(self):
        """This file's number on the device it is on."""
        from interp.value import mk_int

        self._check_open("inode")
        return mk_int(os.fstat(self._fd).st_ino, "i64")

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

        self._check_open("read_file")
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

    def write(self, data):
        """Write bytes to the file, in full.

        Args:
            data: a byte[]/u8[] ArrayValue, a Bytes buffer, a str, or
                  raw Python bytes.

        Writing is a statement rather than a value-producing
        expression, so nothing is returned; a write that cannot
        complete raises.
        """
        from interp.value import ArrayValue, IntValue, UnitValue, none

        self._check_open("write")
        raw = data
        if isinstance(raw, ArrayValue):
            out = bytearray()
            for el in raw.elements:
                inner = el.inner if isinstance(el, UnitValue) else el
                if not isinstance(inner, IntValue):
                    raise TypeError(
                        "file.write: the array must hold bytes, but an "
                        f"element is {type(inner).__name__}")
                if inner.value < 0 or inner.value > 255:
                    raise ValueError(
                        f"file.write: {inner.value} does not fit a byte")
                out.append(inner.value)
            raw = bytes(out)
        elif isinstance(raw, Bytes):
            raw = bytes(raw.data)
        elif isinstance(raw, str):
            raw = raw.encode("utf-8")
        if not isinstance(raw, (bytes, bytearray)):
            raise TypeError(
                f"file.write expects bytes, a byte array, or a string, "
                f"got {type(data).__name__}")
        view = memoryview(bytes(raw))
        while view:
            n = os.write(self._fd, view)
            view = view[n:]
        return none()

    def writev(self, runs):
        """Write the runs in one call, as writev(2) does.

        The argument is an array of `std.iovec`, each made by
        `std.iov`, and each becomes one entry of the vector the kernel
        is handed.  The runs reach the file in the order the array has
        them and with nothing between them, which is what makes this
        the way to write a binary format whose parts are described
        rather than assembled: the description stays typed and the
        kernel does the joining.

        Writing is a statement rather than a value-producing
        expression, so nothing is returned; a write that cannot
        complete raises.
        """
        from interp.value import ArrayValue, ObjectValue, UnitValue, none

        self._check_open("writev")
        held = runs.obj if isinstance(runs, ObjectValue) else runs
        if not isinstance(held, ArrayValue):
            raise TypeError(
                "file.writev: the runs to write are one array of "
                "std.iovec; std.iov makes one")
        chunks = []
        for index, element in enumerate(held.elements):
            run = element
            while isinstance(run, (UnitValue, ObjectValue)):
                run = (run.inner if isinstance(run, UnitValue) else run.obj)
            if not isinstance(run, IoVec):
                raise TypeError(
                    f"file.writev: run {index} is not one std.iov made; "
                    f"it is {type(run).__name__}")
            chunks.append(run.data)
        # A short writev leaves the remaining pieces unwritten, so the
        # loop resumes from wherever the kernel stopped rather than
        # trusting one call to place everything.
        views = [memoryview(c) for c in chunks if c]
        while views:
            written = os.writev(self._fd, views)
            while written and views:
                if written >= len(views[0]):
                    written -= len(views[0])
                    views.pop(0)
                else:
                    views[0] = views[0][written:]
                    written = 0
        return none()

    def chmod(self, mode):
        """Set the file's permission bits, e.g. 0o755 for an executable."""
        self._check_open("chmod")
        os.fchmod(self._fd, mode)
        from interp.value import none
        return none()

    def close(self):
        """Close the file descriptor and make the file unavailable.

        Closing a file that is already closed is an error rather than a
        no-op: the second close says the program has lost track of the
        descriptor's lifetime, and on a descriptor the kernel has since
        reissued it would close an unrelated file.
        """
        self._check_open("close")
        _close(self._fd)
        self._closed = True

    def destroy(self):
        """Release the descriptor because the owning scope has ended.

        Unlike close(), this is not an error on an already-closed file:
        an explicit close is the program saying it is finished early, and
        the scope ending afterwards has nothing left to do.
        """
        if not self._closed:
            _close(self._fd)
            self._closed = True


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

# Replacement-field specifiers, as C++'s std::format has them:
#
#     [[fill]align][sign][#][0][width][.precision][type][flags]
#
# The type letters are C++'s, and Python's are close enough that the
# work is handed to it once the parts NGPL adds have been taken off.
#
# NGPL adds two trailing flags, for the two things a value here carries
# that a C++ value does not:
#
#     t   say the type, as the suffix that would produce it
#     u   leave off the unit
_NGPL_FORMAT_FLAGS = "tu"


def _split_format_spec(spec: str) -> tuple[str, str]:
    """Separate the C++ part of a specifier from the flags NGPL adds."""
    flags = ""
    while spec and spec[-1] in _NGPL_FORMAT_FLAGS:
        # A type letter is not a flag, however it is spelled: only a
        # trailing run of flag letters is taken.
        flags = spec[-1] + flags
        spec = spec[:-1]
    return spec, flags


def _int_type_suffix(value) -> str:
    """The suffix that would produce this number, or nothing if untyped."""
    width = getattr(value, "width", "int")
    return "" if width in ("int", "float", "untyped") else width


def _render_template(fmt: str, args, where: str) -> str:
    """Substitute values into a template's replacement fields.

    Shared by std.format and std.print, so a value reads the same
    however it reaches the output.
    """
    from interp.eval import unwrap_optional
    from interp.value import (IntValue, FloatValue, BoolValue, StrValue,
                              CharValue,
                              ObjectValue, ArrayValue, HashValue, SetValue,
                              TupleValue,
                              EnumValue, ExpectedValue, NoneValue,
                              TypeValue, FuncValue, LambdaValue, UnitValue,
                              RangeValue)
    def _fmt_value(v, spec: str = "") -> str:
        core, flags = _split_format_spec(spec)
        uv = unwrap_optional(v)
        if isinstance(uv, UnitValue):
            inner = _fmt_value(uv.inner, spec)
            if "u" in flags:
                return inner
            return inner + " " + uv.unit.display_name
        if "t" in flags and isinstance(uv, (IntValue, FloatValue)):
            return _fmt_value(uv, core) + _int_type_suffix(uv)
        spec = core
        if isinstance(uv, ExpectedValue):
            if uv.is_ok():
                return _fmt_value(uv.ok_value, spec)
            return _fmt_value(uv.err_value, spec)
        if isinstance(uv, NoneValue):
            return "\N{EMPTY SET}"
        if isinstance(uv, BoolValue):
            text = "true" if uv.value else "false"
            return format(text, spec) if spec else text
        if isinstance(uv, StrValue):
            return format(uv.value, spec) if spec else uv.value
        if isinstance(uv, CharValue):
            # Written out as itself, the way a string is: the quotes a
            # character is displayed with are for reading a value back,
            # not for putting one in a line of output.
            return format(uv.char, spec) if spec else uv.char
        if isinstance(uv, EnumValue):
            return uv.display()
        if isinstance(uv, TypeValue):
            return uv.name
        if isinstance(uv, IntValue):
            if not spec:
                return str(uv.value)
            if spec.endswith("c"):
                return format(chr(uv.value), spec[:-1] or "")
            try:
                return format(uv.value, spec)
            except ValueError:
                raise TypeError(
                    f"'{spec}' does not format an integer")
        if isinstance(uv, FloatValue):
            if not spec:
                return repr(uv.value)
            try:
                return format(uv.value, spec)
            except ValueError:
                raise TypeError(
                    f"'{spec}' does not format a floating-point number")
        if isinstance(uv, TupleValue):
            inner = ", ".join(_fmt_value(e) for e in uv.elements)
            return "[" + inner + "]"
        if isinstance(uv, ObjectValue):
            obj = uv.obj
            if isinstance(obj, ArrayValue):
                # Through values(): a view has no elements list of its
                # own, and reading the attribute crashes on one.
                inner = ", ".join(_fmt_value(e) for e in obj.values())
                return "[" + inner + "]"
            if isinstance(obj, HashValue):
                inner = ", ".join(f"{_fmt_value(k)}: {_fmt_value(v)}"
                                  for k, v in obj.pairs())
                return f"\N{LEFT DOUBLE PARENTHESIS}{inner}\N{RIGHT DOUBLE PARENTHESIS}"
            if isinstance(obj, SetValue):
                inner = ", ".join(_fmt_value(v) for v in obj.values())
                return f"\N{LEFT DOUBLE PARENTHESIS}{inner}\N{RIGHT DOUBLE PARENTHESIS}"
            if isinstance(obj, Bytes):
                return "[" + ", ".join(str(b) for b in obj.data) + "]"
            return f"<{type(obj).__name__}>"
        if isinstance(uv, (FuncValue, LambdaValue)):
            # A function is applied, not written out: reaching here
            # means the program printed the wrong thing, most often a
            # partial application it believed was a finished call.
            if (isinstance(uv, LambdaValue)
                    and uv.partial_func is not None):
                n = len(uv.params)
                raise coded(2264, TypeError(
                    f"'{{}}' met a partial application of "
                    f"'{uv.partial_func.name}' that still waits for {n} "
                    f"argument{'s' if n != 1 else ''}, not a value; "
                    f"apply the rest before printing"))
            raise TypeError(
                "'{}' met a function, not a value; a function is "
                "applied, not written out")
        if isinstance(uv, RangeValue):
            # The language's own spelling, not the implementation's.
            return uv.display()
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
            if arg_idx >= len(args):
                raise coded(2265, TypeError(
                    f"{where}: not enough arguments (need at least {arg_idx + 1}, "
                    f"got {len(args)})"))
            result.append(_fmt_value(args[arg_idx], spec))
            arg_idx += 1
            i = end + 1
        elif ch == "}" and i + 1 < len(fmt) and fmt[i + 1] == "}":
            result.append("}")
            i += 2
        else:
            result.append(ch)
            i += 1

    return "".join(result)


class ImplementationInfo:
    """What `std.implementation` answers: which implementation this is.

    A test conditionalizes on these members where the implementations
    are allowed to differ, and a comptime check (static_assert) may
    read them, since what they hold is settled before anything runs.
    The compiler publishes the same members about itself, so one test
    suite serves every implementation.
    """

    __slots__ = ()

    name = "ngpli"              # the bootstrap interpreter
    language = "bootstrap"      # the subset of NGPL it implements
    interpreter = True
    compiled = False


class Executable:
    """One output a recipe asked for: std.Build.Executable{…}.

    A field the recipe did not name is empty, and what an empty one
    means is settled by whoever builds it -- the compiler, from what
    the command line said and from what the build holds.
    """

    __slots__ = ("name", "root_source_file", "output_dir", "target",
                 "optimize")

    FIELDS: tuple[str, ...] = ("name", "root_source_file", "output_dir",
                               "target", "optimize")

    # The one field that holds a number rather than a name: the level
    # this executable is built at, or None where it says nothing and
    # what -O said stands.
    NUMBERS: tuple[str, ...] = ("optimize",)

    def __init__(self, name: str = "", root_source_file: str = "",
                 output_dir: str = "", target: str = "",
                 optimize: int | None = None):
        self.name = name
        self.root_source_file = root_source_file
        self.output_dir = output_dir
        self.target = target
        self.optimize = optimize

    def display(self) -> str:
        return f"std.Build.Executable{{name: \"{self.name}\"}}"


# What the machine underfoot is called where a target is named, in the
# compiler's own spelling: `uname` says amd64 or x86_64 and a target is
# x86-64, and a recipe reading b.host_target must read the same string
# under both implementations.  A machine no target claims answers as
# itself, since a recipe comparing against it will not match either way.
_TARGET_SPELLING = {
    "x86_64": "x86-64", "amd64": "x86-64",
    "i386": "i386", "i486": "i386", "i586": "i386", "i686": "i386",
    "aarch64": "aarch64", "arm64": "aarch64",
    "armv7l": "arm", "armv6l": "arm", "arm": "arm",
    "riscv64": "riscv64", "riscv32": "riscv32",
}


def host_target() -> str:
    """The target name for the machine this is running on."""
    import platform
    machine = platform.machine()
    return _TARGET_SPELLING.get(machine, machine)


class Options:
    """What the command line said, as a recipe reads it.

    One data member per option whose value a recipe could want, each an
    optional: absent where the command line said nothing.  A recipe is
    handed this rather than a parameter per option so that an option
    added later leaves every recipe's signature as it was.

    The interpreter builds nothing, so the one it hands over says
    nothing: it is there to be read, and to hold a recipe to the rules
    for reading it.
    """

    __slots__ = ("_output", "_target", "_optimize", "_path")

    MEMBERS: tuple[str, ...] = ("output", "target", "optimize", "path")

    def __init__(self, output: str | None = None, target: str | None = None,
                 optimize: int | None = None, path: str | None = None):
        self._output = output
        self._target = target
        self._optimize = optimize
        self._path = path

    @staticmethod
    def _said(what: str | None):
        """What the command line said, as the recipe reads it: ∅ where
        it said nothing, and the string it said where it did."""
        from interp.value import SomeValue, mk_str, none
        return none() if what is None else SomeValue(mk_str(what))

    @property
    def output(self):
        return self._said(self._output)

    @property
    def target(self):
        return self._said(self._target)

    @property
    def path(self):
        return self._said(self._path)

    @property
    def optimize(self):
        """The level -O asked for: a number, ∅ where it was not given.

        Untyped, as a level written on the command line is: what holds
        it settles how wide it is.
        """
        from interp.value import SomeValue, mk_int, none
        return (none() if self._optimize is None
                else SomeValue(mk_int(self._optimize)))


class Build:
    """What a @build recipe declares its build on.

    A recipe is handed one and adds to it: an executable for each thing
    to be built, the paths a source is looked for along, the flags the
    compiler is asked for.  `output_dir` is where an executable that
    names none goes, and `host_target` is what the compiler builds for
    when nothing says otherwise -- the first a recipe may write, the
    second only read.

    Acting on any of it belongs to the compiler; the interpreter reads
    the recipe to hold it to the rules and to run what it computes.
    """

    __slots__ = ("_paths", "_flags", "_executables", "output_dir",
                 "host_target")

    def __init__(self, host_target: str = ""):
        self._paths: list[str] = []
        self._flags: list[str] = []
        self._executables: list[Executable] = []
        self.output_dir: str = ""
        self.host_target: str = host_target

    def _one_str(self, args, who):
        from interp.eval import unwrap_optional
        from interp.value import StrValue, runtime_type_of
        if len(args) != 1:
            raise TypeError(f"std.Build.{who} takes the one string")
        v = unwrap_optional(args[0])
        if not isinstance(v, StrValue):
            raise TypeError(
                f"std.Build.{who} is told a string, not {runtime_type_of(v)}")
        return v.value

    def add_executable(self, args):
        from interp.value import none, ObjectValue
        from interp.eval import unwrap_optional
        if len(args) != 1:
            raise TypeError(
                "std.Build.add_executable takes the one std.Build.Executable")
        v = unwrap_optional(args[0])
        cfg = v.obj if isinstance(v, ObjectValue) else v
        if not isinstance(cfg, Executable):
            raise TypeError(
                "std.Build.add_executable is told a std.Build.Executable")
        if not cfg.name:
            raise TypeError(
                "an executable is named: its 'name' is what the file is called")
        if not cfg.root_source_file:
            raise TypeError(
                "an executable names the file it is rooted in: its "
                "'root_source_file'")
        self._executables.append(cfg)
        return none()

    def search_path(self, args):
        from interp.value import none
        self._paths.append(self._one_str(args, "search_path"))
        return none()

    def flag(self, args):
        from interp.value import none
        self._flags.append(self._one_str(args, "flag"))
        return none()


# ---------------------------------------------------------------------------
# std.hash -- digests, one-shot and a byte at a time
# ---------------------------------------------------------------------------

def _hash_message(arg, who: str) -> bytes:
    """The message an argument names: a string is its UTF-8, bytes are
    themselves, and a u8[] is the low byte of each element."""
    from interp.eval import unwrap_optional
    from interp.value import ObjectValue, StrValue, IntValue, ArrayValue
    a = unwrap_optional(arg)
    if isinstance(a, ObjectValue):
        if isinstance(a.obj, ArrayValue):
            return bytes(e.value & 0xFF for e in a.obj.elements
                         if isinstance(e, IntValue))
        if isinstance(a.obj, Bytes):
            return bytes(a.obj.data)
        raise TypeError(f"{who} digests a string or its bytes, "
                        f"got {type(a.obj).__name__}")
    if isinstance(a, StrValue):
        return a.value.encode("utf-8")
    raise TypeError(f"{who} digests a string or its bytes, "
                    f"got {type(a).__name__}")


def _digest_value(raw: bytes):
    """A digest as what a program can hold: its bytes, most significant
    first.  Not a number -- no sized type the language has keeps 256
    bits, so a program handed one as an integer could not keep it."""
    from interp.value import ObjectValue, ArrayValue, mk_int
    return ObjectValue(ArrayValue([mk_int(b, "u8") for b in raw],
                                  element_type="u8", fixed_size=len(raw)))


class HashHandle:
    """One digest being computed, a piece at a time.

    What start() answers.  The point of it is that a program need not
    hold the whole of what it is hashing: a file larger than memory, a
    stream that arrives over time, or -- the case that brought this
    about -- a compiler's bill of materials, which is a quarter of a
    megabyte of tokens that would otherwise be gathered into one array
    before any of it could be hashed.
    """

    def __init__(self, name: str, ctor):
        self.name = name
        self._h = ctor()
        self._spent = False

    def _live(self, what: str):
        if self._spent:
            raise RuntimeError(
                f"{what} on a {self.name} handle whose digest was already "
                f"taken; digest() ends the handle")

    def update(self, args):
        """update(x) — add x to what is being digested."""
        from interp.value import NoneValue
        if len(args) != 1:
            raise TypeError("update(x) takes exactly 1 argument")
        self._live("update")
        self._h.update(_hash_message(args[0], f"{self.name}.update"))
        return NoneValue()

    def digest(self, args):
        """digest() — the digest of everything added, and the end of the
        handle.  What it held is dropped here rather than whenever the
        collector gets to it, so a message that was worth hashing is not
        left lying about afterwards."""
        if args:
            raise TypeError("digest() takes no arguments")
        self._live("digest")
        raw = self._h.digest()
        self._spent = True
        self._h = None
        return _digest_value(raw)


class Sha256Algorithm:
    """std.hash.sha256 — the algorithm, as a namespace.

    Every algorithm answers the same two: digest(x) for a message
    already in hand, and start() for one that is not.  Another
    algorithm is another namespace beside this one, not two more names
    inside std.hash.
    """

    name = "sha256"

    def digest(self, args):
        """digest(x) — the SHA-256 of x, as its thirty-two bytes."""
        if len(args) != 1:
            raise TypeError("digest(x) takes exactly 1 argument")
        return _digest_value(
            hashlib.sha256(_hash_message(args[0], "std.hash.sha256.digest")).digest())

    def start(self, args):
        """start() — a handle to feed a message to a piece at a time."""
        from interp.value import ObjectValue
        if args:
            raise TypeError("start() takes no arguments")
        return ObjectValue(HashHandle("sha256", hashlib.sha256))


class HashModule:
    """std.hash — one namespace per algorithm."""

    def __init__(self):
        self.sha256 = Sha256Algorithm()


class StdModule:
    """The std module providing built-in runtime services.

    This is the entry point for all runtime functionality available to
    NGPL programs. It is initialized once when the interpreter starts
    and its methods are registered as builtin functions in the global env.
    """

    # The tolerance the approximate comparisons use, following APL's
    # ⎕CT.  Two numbers are alike when they differ by no more than this
    # fraction of the larger of them, so it is relative rather than
    # absolute and nothing but zero is alike to zero.
    comparison_tolerance = 1e-13

    def __init__(self):
        self._allocator = MmapAllocator()
        self._fs = None  # lazy-initialized fs object
        self._heap = None  # lazy-initialized heap submodule
        self._arena = None  # lazy-initialized arena submodule
        self._env = None  # lazy-initialized env submodule
        self._sys = None  # lazy-initialized sys submodule
        self._process = None  # lazy-initialized process submodule
        self._stdout_file = StdoutFile()
        self._syntax = None  # lazy-initialized syntax submodule
        self.args = ArgsModule()
        self.implementation = ImplementationInfo()
        self.hash = HashModule()

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

    @property
    def process(self):
        """Lazy-access to what the kernel recorded about this process."""
        if self._process is None:
            self._process = ProcessModule()
        return self._process

    # ------------------------------------------------------------------
    # Process termination
    # ------------------------------------------------------------------

    def exit(self, code=0):
        """exit(code) — terminate the program with the given exit code.

        A POSIX exit status is a single byte, so a code outside 0…255 is
        rejected rather than silently truncated: a program asking to exit
        with 300 and being reported as having exited with 44 is a bug the
        language should catch, not propagate.

        Args:
            code: the exit status, 0…255.  Defaults to 0.

        Raises:
            ProgramExit: always; the interpreter turns it into the
                process exit status.
        """
        from interp.errors import ProgramExit
        from interp.value import IntValue, UnitValue

        if isinstance(code, UnitValue):
            code = code.inner
        if isinstance(code, IntValue):
            code = code.value
        if isinstance(code, bool) or not isinstance(code, int):
            raise coded(2266, TypeError("std.exit: exit code must be an integer"))
        if not 0 <= code <= 255:
            raise coded(2267, TypeError(
                f"std.exit: exit code {code} is outside the range 0\N{HORIZONTAL ELLIPSIS}255 "
                f"that a process can report"))
        raise ProgramExit(code)

    def abort(self, signal_number=None):
        """abort(signal) — terminate the program by raising a signal.

        The signal is delivered to the process with its handler reset to
        the default, so the program really does die by it and the parent
        sees the termination signal in its wait status.

        A missing, zero, or invalid signal number falls back to SIGABRT.
        That fallback is deliberate: abort is called when a program has
        already decided it cannot continue, and refusing to terminate
        because the requested signal was wrong would be the worse
        failure.

        Args:
            signal_number: the signal to raise, or None for SIGABRT.

        Raises:
            ProgramAbort: always; the interpreter delivers the signal
                after reporting where the abort came from.
        """
        from interp.errors import ProgramAbort
        from interp.value import IntValue, NoneValue, UnitValue

        if isinstance(signal_number, UnitValue):
            signal_number = signal_number.inner
        if isinstance(signal_number, IntValue):
            signal_number = signal_number.value
        if isinstance(signal_number, NoneValue) or signal_number is None:
            signal_number = 0
        if isinstance(signal_number, bool) or not isinstance(signal_number, int):
            raise coded(2268, TypeError("std.abort: signal must be an integer"))
        raise ProgramAbort(resolve_abort_signal(signal_number))

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

        return mk_str(_render_template(fmt, fmt_args, "std.format"))

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

    # ------------------------------------------------------------------
    # Trigonometry
    # ------------------------------------------------------------------

    # The ratio a circle's circumference bears to its diameter, to as
    # many places as f64 keeps.
    π = 3.141592653589793

    def _one_float(self, args, who: str) -> float:
        """The single number a one-argument function was handed."""
        from interp.eval import unwrap_optional
        from interp.value import IntValue, FloatValue, UnitValue

        if len(args) != 1:
            raise TypeError(f"{who}(x) takes exactly 1 argument")
        arg = unwrap_optional(args[0])
        if isinstance(arg, UnitValue):
            arg = arg.inner
        if not isinstance(arg, (IntValue, FloatValue)):
            raise TypeError(f"{who} expects a number, got "
                            f"{type(arg).__name__}")
        return float(arg.value)

    def sin(self, args):
        """sin(x) -- the sine of an angle in radians."""
        from interp.value import FloatValue

        return FloatValue(_math.sin(self._one_float(args, "sin")), "f64")

    def cos(self, args):
        """cos(x) -- the cosine of an angle in radians."""
        from interp.value import FloatValue

        return FloatValue(_math.cos(self._one_float(args, "cos")), "f64")

    def sinpi(self, args):
        """sinpi(x) -- the sine of x×π, which is exact at every whole x.

        sin(x×π) has to round x×π first, and π is not a number f64
        holds, so sin(1.0×π) is not zero.  Taking the turns rather than
        the radians keeps the whole ones whole.
        """
        from interp.value import FloatValue

        x = self._one_float(args, "sinpi")
        whole = _math.floor(x)
        value = _math.sin((x - whole) * _math.pi)
        if int(whole) % 2:
            value = -value
        return FloatValue(0.0 + value, "f64")

    @property
    def syntax(self):
        """Lazy-access to the submodule that builds program text."""
        if self._syntax is None:
            self._syntax = SyntaxModule()
        return self._syntax

    def iov(self, args):
        """iov(x) -- the run of bytes x amounts to, ready to be written.

        A run is made from one of three things: a byte array, which is
        already its own bytes; a struct with a defined layout, which is
        packed as that layout describes; or an array of such structs --
        a table -- which is packed element after element, as C lays an
        array out.  The bytes are settled here, where the value is, so
        that a run handed to `writev` later is a run and not a promise.
        """
        from interp.pack import PackError, collect_lookup, iov_bytes
        from interp.value import ObjectValue

        if len(args) != 1:
            raise TypeError("iov(x) takes exactly 1 argument")
        try:
            raw = iov_bytes(args[0], collect_lookup(args), 0)
        except PackError as e:
            raise TypeError(f"std.iov: {e}") from None
        return ObjectValue(IoVec(raw))

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

    def _write_formatted(self, args, where: str, newline: bool):
        """Render a template and write it to stdout.

        Shared by print and println, which differ only in whether a
        newline follows what the template produced.
        """
        from interp.eval import unwrap_optional
        from interp.value import StrValue, none, runtime_type_of

        if not args:
            # An empty template is worth suggesting only where it does
            # something: for println it is how a blank line is written,
            # while for print it produces nothing at all.
            hint = ('; std.println("") writes an empty line'
                    if newline else "")
            raise TypeError(
                f"{where}(fmt, ...) requires a format string{hint}")
        template = unwrap_optional(args[0])
        if not isinstance(template, StrValue):
            raise TypeError(
                f"{where}: the first argument is the format string, but "
                f"this one is {runtime_type_of(template)}; to write a value "
                f"on its own, say {where}(\"{{}}\", \N{HORIZONTAL ELLIPSIS})")
        output = _render_template(template.value, args[1:], where)
        if newline:
            output += "\n"
        os.write(1, output.encode("utf-8"))
        # Writing is a statement, not a value-producing expression;
        # returning the empty string would make the REPL echo it after
        # every call.
        return none()

    def print(self, args):
        """print(fmt, ...) — write formatted text to stdout.

        Takes a template first, as C++'s std::print does, and fills its
        replacement fields from the arguments that follow.  The fields
        are the ones std.format reads, so a value looks the same
        whichever way it is written out.

        Nothing follows what the template produced, so consecutive
        calls run together on one line.  std.println is this call with
        a newline after it, which is what a line of output wants.

        Args:
            args[0]: StrValue — the template.
            args[1:]: values to substitute into it.

        Returns:
            NoneValue.
        """
        return self._write_formatted(args, "std.print", newline=False)

    def println(self, args):
        """println(fmt, ...) — write a formatted line to stdout.

        std.print with a newline after it.

        Args:
            args[0]: StrValue — the template.
            args[1:]: values to substitute into it.

        Returns:
            NoneValue.
        """
        return self._write_formatted(args, "std.println", newline=True)


class SyntaxModule:
    """Building pieces of the program that no quote can spell.

    A quote writes what is written in it.  What it cannot write is a
    piece whose shape depends on a value -- an application of however
    many arguments are left after one is taken out, say -- and that is
    what this is for.
    """

    def funcall(self, args):
        """funcall(head, arguments) -- apply one thing to the others.

        `head` is what to apply, as `※` writes it or as `head()`
        answers it: an operator, a function name, a method.  What comes
        back is the piece of the program that applies it.

        An operator handed more than two arguments is applied to them
        the way writing them out would be, from the left: three
        arguments to ※\N{MULTIPLICATION SIGN} answer (a \N{MULTIPLICATION SIGN} b) \N{MULTIPLICATION SIGN} c.  That is what
        makes one call able to put back a product that has lost a
        factor, whatever it had before.
        """
        from interp.ast import BinOp, UnaryOp, FuncCall, MethodCall, \
            OperatorRef, VarRef, GetAttr
        from interp.eval import unwrap_optional
        from interp.value import ArrayValue, ObjectValue, SyntaxValue

        if len(args) != 2:
            raise TypeError(
                "funcall(head, arguments) takes exactly 2 arguments")
        head = unwrap_optional(args[0])
        held = unwrap_optional(args[1])
        if not isinstance(head, SyntaxValue) or head.is_block:
            raise TypeError(
                "funcall applies a piece of the program, such as ※\N{MULTIPLICATION SIGN} or "
                "what head() answered")
        if not (isinstance(held, ObjectValue)
                and isinstance(held.obj, ArrayValue)):
            raise TypeError("funcall expects an array of syntax to apply to")
        pieces = [unwrap_optional(v) for v in held.obj.values()]
        for piece in pieces:
            if not isinstance(piece, SyntaxValue) or piece.is_block:
                raise TypeError(
                    "funcall applies something to expressions, and one of "
                    "these is not one")
        trees = [p.node for p in pieces]
        applied = head.node
        if isinstance(applied, OperatorRef):
            if not trees:
                raise TypeError(
                    f"funcall was handed the operator {applied.op} and "
                    f"nothing to apply it to")
            if len(trees) == 1:
                return SyntaxValue(node=UnaryOp(applied.op, trees[0]))
            made = trees[0]
            for tree in trees[1:]:
                made = BinOp(applied.op, made, tree)
            return SyntaxValue(node=made)
        if isinstance(applied, VarRef):
            return SyntaxValue(node=FuncCall(applied.name, trees))
        if isinstance(applied, GetAttr):
            return SyntaxValue(node=MethodCall(applied.obj, applied.attr,
                                               trees))
        raise TypeError(
            "funcall applies an operator, a function or a method, and this "
            "is none of those")


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
            raise coded(2757, IndexError(
                f"std.args.get: index {i} out of range "
                f"(count {len(self._params)})"))
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
        from interp.value import mk_str, none, some
        key = _as_name(name, "std.env.get")
        raw = _getenv(key.encode("utf-8"))
        if raw is None:
            return none()
        # Marked present so that an empty value is still a value in a
        # boolean context: FOO= is set, and must not read as unset.
        return some(mk_str(_decode(raw)))

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


# The auxiliary vector's keys, from <elf.h>.  Only the ones the
# language answers for are named here.
_AT_PAGESZ = 6
_AT_UID = 11
_AT_EUID = 12
_AT_GID = 13
_AT_EGID = 14
_AT_SECURE = 23
_AT_EXECFN = 31

_auxv_cache: dict[int, int] | None = None


def _auxv() -> dict[int, int]:
    """The ELF auxiliary vector the kernel left for this process.

    `/proc/self/auxv` is the vector itself, not a rendering of it: pairs
    of native words, a key and its value, ending at a key of AT_NULL.
    The vector is written once, when the kernel starts the process, and
    never changes, so it is read once and kept.
    """
    global _auxv_cache
    if _auxv_cache is not None:
        return _auxv_cache
    try:
        with open("/proc/self/auxv", "rb") as handle:
            raw = handle.read()
    except OSError:
        raise TypeError(
            "the auxiliary vector cannot be read; /proc/self/auxv is "
            "where the kernel leaves it") from None
    stride = struct.calcsize("@NN")
    found: dict[int, int] = {}
    offset = 0
    while offset + stride <= len(raw):
        key, value = struct.unpack_from("@NN", raw, offset)
        offset += stride
        if key == 0:
            break
        found[key] = value
    _auxv_cache = found
    return found


def _auxv_at(key: int, who: str) -> int:
    """One entry of the vector, or an error naming what was missing."""
    vector = _auxv()
    if key not in vector:
        raise TypeError(
            f"the auxiliary vector carries no {who}; this kernel did "
            f"not supply it")
    return vector[key]


class ProcessModule:
    """What the kernel recorded about this process when it started it.

    Every member here comes from the ELF auxiliary vector rather than
    from a system call made later, so what they answer is the process
    as it was executed: the identity `execve` settled on, before
    anything the program itself might do.  All are read-only.

    Under the interpreter the process is the interpreter's own, so
    `exec_filename` names the interpreter rather than the source it is
    running; the compiled program names itself.  The rest -- the page
    size, the four identities, and whether the kernel started the
    program with elevated privilege -- describe the same process either
    way and agree between them.
    """

    __slots__ = ()

    @property
    def pagesize(self):
        """The page size, in bytes: AT_PAGESZ."""
        from interp.units import BUILTIN_UNITS
        from interp.value import UnitValue, IntValue
        return UnitValue(IntValue(_auxv_at(_AT_PAGESZ, "page size"), "i64"),
                         BUILTIN_UNITS["byte"])

    @property
    def uid(self):
        """The real user id: AT_UID."""
        from interp.value import IntValue
        return IntValue(_auxv_at(_AT_UID, "user id"), "u32")

    @property
    def euid(self):
        """The effective user id: AT_EUID."""
        from interp.value import IntValue
        return IntValue(_auxv_at(_AT_EUID, "effective user id"), "u32")

    @property
    def gid(self):
        """The real group id: AT_GID."""
        from interp.value import IntValue
        return IntValue(_auxv_at(_AT_GID, "group id"), "u32")

    @property
    def egid(self):
        """The effective group id: AT_EGID."""
        from interp.value import IntValue
        return IntValue(_auxv_at(_AT_EGID, "effective group id"), "u32")

    @property
    def secure(self):
        """Whether the kernel raised privilege to start this program.

        AT_SECURE is set when the program was executed setuid, setgid or
        with capabilities it did not already hold, which is when a
        program must not trust what it was handed.
        """
        from interp.value import mk_bool
        return mk_bool(_auxv_at(_AT_SECURE, "secure flag") != 0)

    @property
    def exec_filename(self):
        """The path `execve` was given for this process: AT_EXECFN.

        The vector holds the address of the bytes, which lie above the
        environment on the process's own initial stack, so reading them
        is reading this process's memory.
        """
        from interp.value import mk_str
        address = _auxv_at(_AT_EXECFN, "executable name")
        if address == 0:
            return mk_str("")
        return mk_str(_decode(ctypes.cast(address, ctypes.c_char_p).value or b""))


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
