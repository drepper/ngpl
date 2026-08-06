"""Environment management for variable scoping.

Maintains a stack of frames, each mapping names to runtime values.
Supports nested scopes created by function calls.
"""

from interp.value import Value


class Env:
    """Variable environment with nested scopes.

    The global frame holds module-level bindings (including builtins).
    Each function call pushes a new local frame and pops it on return.
    """

    def __init__(self, parent=None):
        self._frames = [{}]  # stack of dicts: name → Value
        self._mutable_globals: set[str] = set()
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

    def pop_frame(self):
        """Pop the top local frame. Must not be called on the global frame."""
        if len(self._frames) <= 1:
            raise RuntimeError("cannot pop the global frame")
        return self._frames.pop()

    # ------------------------------------------------------------------
    # Variable access (with scope lookup)
    # ------------------------------------------------------------------

    def define(self, name: str, value: Value):
        """Define a new variable in the innermost frame."""
        self._frames[-1][name] = value

    def lookup(self, name: str) -> Value:
        """Look up a variable, searching from innermost to outermost frame.

        Args:
            name: the variable name.

        Returns:
            The Value bound to the name.

        Raises:
            KeyError: if the name is not found in any scope.
        """
        for frame in reversed(self._frames):
            if name in frame:
                return frame[name]
        # Check parent environment (for imported modules).
        if self._parent is not None:
            return self._parent.lookup(name)
        raise KeyError(f"undefined variable: {name}")

    def has_local(self, name: str) -> bool:
        """Check if the name is defined in the current (innermost) frame."""
        return name in self._frames[-1]

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
