"""
backstep.tool_registry
~~~~~~~~~~~~~~~~~~~~~~
Global registry of tool callable implementations used for replay.

During replay the CLI walks a session's Actions in seq order and calls
the registered function for each tool name, passing ``**action.args``
as keyword arguments.

Usage::

    from backstep.tool_registry import tool_registry

    def write_file(path: str, content: str) -> str:
        with open(path, "w") as f:
            f.write(content)
        return "ok"

    tool_registry.register("write_file", write_file)

Or via the module-level helper::

    import backstep

    @backstep.register_tool("read_file")
    def read_file(path: str) -> str:
        with open(path) as f:
            return f.read()
"""

from __future__ import annotations

from typing import Callable


class ToolRegistry:
    """Maps tool names to callable implementations for replay."""

    def __init__(self) -> None:
        self._tools: dict[str, Callable] = {}

    def register(self, tool_name: str, fn: Callable) -> None:
        """Register *fn* as the callable for *tool_name*.

        During replay *fn* is called as ``fn(**action.args)``.
        Calling this a second time for the same name replaces the
        previous registration.
        """
        self._tools[tool_name] = fn

    def get(self, tool_name: str) -> Callable | None:
        """Return the callable for *tool_name*, or ``None``."""
        return self._tools.get(tool_name)

    def names(self) -> list[str]:
        """Return the list of registered tool names."""
        return list(self._tools.keys())


# ---------------------------------------------------------------------------
# Global singleton — imported by cli and __init__
# ---------------------------------------------------------------------------

tool_registry = ToolRegistry()
