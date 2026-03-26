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
"""

from ledger.interceptor import LedgerSession
from ledger.store import LedgerStore


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


__all__ = ["session", "LedgerSession", "LedgerStore"]
