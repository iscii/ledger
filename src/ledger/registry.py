"""
ledger.registry
~~~~~~~~~~~~~~~
Global inverse registry — maps tool names to undo functions and tracks
which tools are irreversible (committed).

Usage::

    from ledger.registry import registry

    # Register a custom inverse
    registry.register("my_tool", lambda args, result: undo_it(args))

    # Mark a tool as irreversible
    registry.register_committed("send_email")

Built-in inverses (registered automatically on import):
    write_file  → delete the file at args["path"]
    create_dir  → rmdir args["path"] (no-op if non-empty)
"""

from __future__ import annotations

import os
from typing import Callable


class InverseRegistry:
    """Maps tool names to inverse (undo) functions."""

    def __init__(self) -> None:
        self._inverses: dict[str, Callable] = {}
        self._committed: set[str] = set()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, tool_name: str, fn: Callable) -> None:
        """Register *fn* as the undo function for *tool_name*.

        *fn* must accept ``(args: dict, result: dict) -> None``.
        Calling this a second time for the same tool replaces the
        previous registration.
        """
        self._inverses[tool_name] = fn

    def register_committed(self, tool_name: str) -> None:
        """Mark *tool_name* as irreversible.

        Committed tools are captured normally but cannot be rolled back.
        Their :attr:`Action.status` is set to ``"committed"`` and
        :attr:`Action.reversible` to ``False`` at capture time.
        """
        self._committed.add(tool_name)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_inverse(self, tool_name: str) -> Callable | None:
        """Return the inverse function for *tool_name*, or ``None``."""
        return self._inverses.get(tool_name)

    def is_committed(self, tool_name: str) -> bool:
        """Return ``True`` if *tool_name* is marked as irreversible."""
        return tool_name in self._committed


# ---------------------------------------------------------------------------
# Global singleton — imported by interceptor and __init__
# ---------------------------------------------------------------------------

registry = InverseRegistry()


# ---------------------------------------------------------------------------
# Built-in inverses
# ---------------------------------------------------------------------------

def _undo_write_file(args: dict, result: dict) -> None:  # noqa: ARG001
    path = args["path"]
    if os.path.exists(path):
        os.remove(path)


def _undo_create_dir(args: dict, result: dict) -> None:  # noqa: ARG001
    path = args["path"]
    try:
        os.rmdir(path)  # only removes empty directories; raises OSError if non-empty
    except OSError:
        pass


registry.register("write_file", _undo_write_file)
registry.register("create_dir", _undo_create_dir)
