"""
ledger — zero-config AI agent action recorder.

Usage::

    import ledger

    with ledger.session("session-01") as session:
        result = my_agent.run(client, "do a task")

    # session.actions contains all captured Action objects

Persist to SQLite::

    with ledger.session("session-01", db="./ledger.db") as session:
        result = my_agent.run(client, "do a task")

Register a custom inverse::

    @ledger.register_inverse("my_tool")
    def undo_my_tool(args: dict, result: dict) -> None:
        ...  # undo whatever my_tool did

Mark a tool as irreversible::

    @ledger.committed("send_email")
    def send_email_tool(args: dict, result: dict) -> None:
        pass  # no-op body; the decorator does the work

Roll back a session::

    from ledger.rollback import RollbackEngine
    engine = RollbackEngine(store, ledger.registry)
    result = engine.rollback("session-01")
"""

from ledger.interceptor import LedgerSession
from ledger.store import LedgerStore
from ledger.registry import InverseRegistry, registry
from ledger.rollback import RollbackEngine, RollbackResult


def session(session_id: str, db: str | None = None) -> LedgerSession:
    """Return a context manager that records all Anthropic tool calls.

    Args:
        session_id: A unique identifier for this execution session.
        db:         Path to a SQLite database file.  If ``None`` (default),
                    Actions are printed to stdout only — nothing is written
                    to disk.

    Returns:
        A :class:`~ledger.interceptor.LedgerSession` context manager.
        On exit, ``session.actions`` holds every captured
        :class:`~ledger.interceptor.Action`.
    """
    return LedgerSession(session_id, db=db)


def register_inverse(tool_name: str):
    """Decorator factory — register a function as the inverse for *tool_name*.

    Example::

        @ledger.register_inverse("write_file")
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
    ``reversible=False``.  :class:`~ledger.rollback.RollbackEngine` will
    skip them.

    Example::

        @ledger.committed("send_email")
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
    "LedgerSession",
    "LedgerStore",
    "InverseRegistry",
    "RollbackEngine",
    "RollbackResult",
]
