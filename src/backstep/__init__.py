"""
backstep — zero-config AI agent action recorder.

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
from backstep.rollback import RollbackEngine, RollbackResult


def session(session_id: str, db: str | None = None) -> BackstepSession:
    """Return a context manager that records all Anthropic tool calls.

    Args:
        session_id: A unique identifier for this execution session.
        db:         Path to a SQLite database file.  If ``None`` (default),
                    Actions are printed to stdout only — nothing is written
                    to disk.

    Returns:
        A :class:`~backstep.interceptor.BackstepSession` context manager.
        On exit, ``session.actions`` holds every captured
        :class:`~backstep.interceptor.Action`.
    """
    return BackstepSession(session_id, db=db)


def register_inverse(tool_name: str):
    """Decorator factory — register a function as the inverse for *tool_name*.

    Example::

        @backstep.register_inverse("write_file")
        def undo_write_file(args: dict, result: dict) -> None:
            os.remove(args["path"])
    """
    def decorator(fn):
        registry.register(tool_name, fn)
        return fn
    return decorator


def committed(tool_name: str):
    """Decorator factory — mark *tool_name* as irreversible.

    Actions captured for this tool will have ``status='committed'`` and
    ``reversible=False``.  :class:`~backstep.rollback.RollbackEngine` will
    skip them.

    Example::

        @backstep.committed("send_email")
        def send_email_tool(args, result):
            pass
    """
    def decorator(fn):
        registry.register_committed(tool_name)
        return fn
    return decorator


__all__ = [
    "session",
    "register_inverse",
    "committed",
    "registry",
    "BackstepSession",
    "BackstepStore",
    "InverseRegistry",
    "RollbackEngine",
    "RollbackResult",
]
