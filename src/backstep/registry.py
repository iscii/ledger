"""
backstep.registry
~~~~~~~~~~~~~~~~~
Global inverse registry — maps tool names to undo functions and tracks
which tools are irreversible (committed).

Usage::

    from backstep.registry import registry

    # Register a custom inverse
    registry.register("my_tool", lambda args, result: undo_it(args))

    # Mark a tool as irreversible
    registry.register_committed("send_email")

Built-in inverses are registered by backstep.inverses.files on import:
    write_file   -> delete the file at args["path"]
    delete_file  -> restore file from result["previous_content"]
    create_dir   -> rmdir args["path"] (no-op if non-empty)
    move_file    -> move back from args["dest"] to args["src"]
    append_file  -> truncate file to result["original_size"] bytes
"""

from __future__ import annotations

from typing import Callable


class InverseRegistry:
    """Maps tool names to inverse (undo) functions."""

    def __init__(self) -> None:
        self._inverses: dict[str, Callable] = {}
        self._committed: set[str] = set()
        self._sources: dict[str, str] = {}   # tool_name -> source label

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        tool_name: str,
        fn: Callable,
        source: str | None = None,
    ) -> None:
        """Register *fn* as the undo function for *tool_name*.

        Args:
            tool_name: The tool whose side-effects *fn* reverses.
            fn:        Callable accepting (args: dict, result: dict) -> None.
            source:    Human-readable label for the plugin that registered this
                       inverse (shown by ``backstep plugins``).  Defaults to
                       "user" when not supplied.
        """
        self._inverses[tool_name] = fn
        self._sources[tool_name] = source or "user"

    def register_committed(self, tool_name: str) -> None:
        """Mark *tool_name* as irreversible."""
        self._committed.add(tool_name)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_inverse(self, tool_name: str) -> Callable | None:
        return self._inverses.get(tool_name)

    def is_committed(self, tool_name: str) -> bool:
        return tool_name in self._committed

    def list_registered(self) -> dict[str, str]:
        """Return {tool_name: source_label} for every registered inverse."""
        return dict(self._sources)


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

registry = InverseRegistry()
