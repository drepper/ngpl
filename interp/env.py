"""Environment management for variable scoping.

Maintains a stack of frames, each mapping names to runtime values.
Supports nested scopes created by function calls.
"""

from interp.value import Value


class Decl:
    """What a definition said a name holds.

    A value can be asked what it is; it cannot be asked what it was
    *declared* to be, and after one assignment the two are no longer the
    same question.  This is the answer to the second one, kept for as
    long as the binding is, so that what may be stored into a name is
    settled where the name was written rather than by whatever it
    happens to hold at the time.
    """

    __slots__ = ("type_name", "unit")

    def __init__(self, type_name: str | None = None, unit=None):
        self.type_name = type_name
        self.unit = unit

    def says_nothing(self) -> bool:
        """Whether the definition stated neither a type nor a unit."""
        return self.type_name is None and self.unit is None


_MISSING = object()


# What an environment that has marked no global shares, so that a call
# frame allocates nothing for a thing it will never use.
_NO_MARKS: frozenset = frozenset()


class Env:
    """Variable environment with nested scopes.

    The global frame holds module-level bindings (including builtins).
    Each function call pushes a new local frame and pops it on return.
    """

    def __init__(self, parent=None):
        self._frames = [{}]  # stack of dicts: name → Value
        # What each definition said, in step with the frame that holds
        # the value, so a name's declaration lasts exactly as long as
        # the name does.
        self._decls: list[dict[str, Decl | None]] = [{}]
        # A call frame never marks a global -- only the one environment
        # the program was installed into does -- so both start as one
        # shared empty set and become the frame's own the first time
        # something is actually marked.  Two allocations on every call
        # is two too many when calls are counted in millions.
        self._mutable_globals = _NO_MARKS
        self._const_globals = _NO_MARKS
        if parent is not None:
            self._parent = parent
        else:
            self._parent = None

    # ------------------------------------------------------------------
    # Frame management
    # ------------------------------------------------------------------

    def push_frame(self):
        """Push a new local frame onto the stack."""
        self._frames.append({})
        self._decls.append({})

    def pop_frame(self):
        """Pop the top local frame. Must not be called on the global frame."""
        if len(self._frames) <= 1:
            raise RuntimeError("cannot pop the global frame")
        self._decls.pop()
        return self._frames.pop()

    # ------------------------------------------------------------------
    # Variable access (with scope lookup)
    # ------------------------------------------------------------------

    def define(self, name: str, value: Value, decl: "Decl | None" = None):
        """Define a new variable in the innermost frame.

        The declaration is replaced along with the value, a definition
        that states nothing saying so, since a `let` that names an
        existing name is a new definition rather than a store into the
        old one.
        """
        self._frames[-1][name] = value
        self._decls[-1][name] = decl

    def update(self, name: str, value: Value):
        """Store into a name that already exists, leaving its declaration.

        What a definition said outlives the value it said it about, so
        an assignment writes the value alone.  `define` would replace
        both, which would let the first store to a name forget what the
        name was declared to hold.
        """
        for frame in reversed(self._frames):
            if name in frame:
                frame[name] = value
                return True
        if self._parent is not None:
            return self._parent.update(name, value)
        return False

    def declaration(self, name: str) -> "Decl | None":
        """What the definition of *name* said, or None where it said nothing."""
        for frame, decls in zip(reversed(self._frames), reversed(self._decls)):
            if name in frame:
                return decls.get(name)
        if self._parent is not None:
            return self._parent.declaration(name)
        return None

    def lookup(self, name: str) -> Value:
        """Look up a variable, searching from innermost to outermost frame.

        Args:
            name: the variable name.

        Returns:
            The Value bound to the name.

        Raises:
            KeyError: if the name is not found in any scope.
        """
        frames = self._frames
        if len(frames) == 1:
            # A call frame that has opened no block of its own, which
            # is most of them.
            v = frames[0].get(name, _MISSING)
            if v is not _MISSING:
                return v
        else:
            for frame in reversed(frames):
                v = frame.get(name, _MISSING)
                if v is not _MISSING:
                    return v
        # Check parent environment (for imported modules).
        parent = self._parent
        if parent is not None:
            return parent.lookup(name)
        raise KeyError(f"undefined variable: {name}")

    def mark_global(self, name: str, *, mutable: bool) -> None:
        """Record that a global is mutable, or that it is const."""
        if mutable:
            if type(self._mutable_globals) is not set:
                self._mutable_globals = set()
            self._mutable_globals.add(name)
        else:
            if type(self._const_globals) is not set:
                self._const_globals = set()
            self._const_globals.add(name)

    def unmark_global(self, name: str) -> None:
        """Forget whatever was recorded about a global, as a redefinition does."""
        if type(self._const_globals) is set:
            self._const_globals.discard(name)
        if type(self._mutable_globals) is set:
            self._mutable_globals.discard(name)

    def has_local(self, name: str) -> bool:
        """Check if the name is defined in the current (innermost) frame."""
        return name in self._frames[-1]

    def is_const_global(self, name: str) -> bool:
        """Return True if *name* is a const global variable."""
        if name in self._const_globals:
            return True
        if self._parent is not None:
            return self._parent.is_const_global(name)
        return False

    def is_mutable_global(self, name: str) -> bool:
        """Return True if *name* is a mutable global variable."""
        if name in self._mutable_globals:
            return True
        if self._parent is not None:
            return self._parent.is_mutable_global(name)
        return False

    def assign(self, name: str, value: Value) -> bool:
        """Assign to the frame where *name* already exists.

        Returns True if the variable was found and updated, False if not
        found in any frame (caller should fall back to define).
        """
        for frame in reversed(self._frames):
            if name in frame:
                frame[name] = value
                return True
        if self._parent is not None:
            return self._parent.assign(name, value)
        return False

    # ------------------------------------------------------------------
    # Copy for function calls
    # ------------------------------------------------------------------

    def copy_for_call(self):
        """Create a new environment inheriting from this one for a function call.

        Returns:
            A new Env whose immediate frame is empty and whose parent
            points into the calling environment's current chain.
        """
        return Env(parent=self)
