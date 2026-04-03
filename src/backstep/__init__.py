"""
backstep -- zero-config AI agent action recorder.

Usage::

    import backstep

    with backstep.session("session-01") as session:
        result = my_agent.run(client, "do a task")

    # session.actions contains all captured Action objects

Persist to SQLite::

    with backstep.session("session-01", db="./backstep.db") as session:
        result = my_agent.run(client, "do a task")

Register a custom inverse::

    @backstep.register_inverse("my_tool")
    def undo_my_tool(args: dict, result: dict) -> None:
        ...  # undo whatever my_tool did

Mark a tool as irreversible::

    @backstep.committed("send_email")
    def send_email_tool(args: dict, result: dict) -> None:
        pass  # no-op body; the decorator does the work

Roll back a session::

    from backstep.rollback import RollbackEngine
    engine = RollbackEngine(store, backstep.registry)
    result = engine.rollback("session-01")
"""

from backstep.interceptor import BackstepSession
from backstep.store import BackstepStore
from backstep.registry import InverseRegistry, registry
from backstep.rollback import RollbackEngine, RollbackResult, FeasibilityResult, ActionFeasibility
from backstep.replay import ReplayEngine, ReplayResult
from backstep.deps import DependencyAnalyzer, DependencyViolation
from backstep.tool_registry import ToolRegistry, tool_registry
from backstep.diff import DiffEngine, DiffResult, ActionDiff


def session(session_id: str, db: str | None = None) -> BackstepSession:
    """Return a context manager that records all Anthropic tool calls."""
    return BackstepSession(session_id, db=db)


def register_inverse(tool_name: str):
    """Decorator factory -- register a function as the inverse for *tool_name*."""
    def decorator(fn):
        registry.register(tool_name, fn)
        return fn
    return decorator


def register_tool(tool_name: str):
    """Decorator factory -- register a callable for replay of *tool_name*."""
    def decorator(fn):
        tool_registry.register(tool_name, fn)
        return fn
    return decorator


def committed(tool_name: str):
    """Decorator factory -- mark *tool_name* as irreversible."""
    def decorator(fn):
        registry.register_committed(tool_name)
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Plugin loader
# ---------------------------------------------------------------------------

def _load_plugins() -> None:
    """Auto-discover and load backstep plugins.

    Phase 1 -- naming convention:
        Any installed package whose import name starts with ``backstep_``
        is imported.  Simply importing it is enough -- the package's
        ``__init__.py`` calls ``backstep.register_inverse()`` etc.

    Phase 2 -- entry points:
        Packages that declare entry points under the groups
        ``backstep.inverses``, ``backstep.adapters``, or
        ``backstep.reporters`` have those entry points loaded and called.
    """
    import pkgutil
    import importlib
    import warnings
    from importlib.metadata import entry_points

    # Phase 1: naming convention (backstep_* prefix)
    for _finder, name, _ispkg in pkgutil.iter_modules():
        if name.startswith("backstep_"):
            try:
                importlib.import_module(name)
            except Exception as exc:  # noqa: BLE001
                warnings.warn(
                    f"Failed to load backstep plugin '{name}': {exc}",
                    stacklevel=2,
                )

    # Phase 2: entry points
    for group in ("backstep.inverses", "backstep.adapters", "backstep.reporters"):
        for ep in entry_points(group=group):
            try:
                ep.load()()
            except Exception as exc:  # noqa: BLE001
                warnings.warn(
                    f"Failed to load backstep entry point '{ep.name}': {exc}",
                    stacklevel=2,
                )


# Load built-in inverses first, then external plugins.
from backstep.inverses import files as _files_plugin  # noqa: E402, F401
_load_plugins()


__all__ = [
    "session",
    "register_inverse",
    "register_tool",
    "committed",
    "registry",
    "tool_registry",
    "BackstepSession",
    "BackstepStore",
    "InverseRegistry",
    "ToolRegistry",
    "RollbackEngine",
    "RollbackResult",
    "FeasibilityResult",
    "ActionFeasibility",
    "ReplayEngine",
    "ReplayResult",
    "DependencyAnalyzer",
    "DependencyViolation",
    "DiffEngine",
    "DiffResult",
    "ActionDiff",
]
