"""
ledger — zero-config AI agent action recorder.

Usage::

    import ledger

    with ledger.session("session-01") as session:
        result = my_agent.run(client, "do a task")

    # session.actions contains all captured Action objects
"""

from ledger.interceptor import LedgerSession


def session(session_id: str) -> LedgerSession:
    """Return a context manager that records all Anthropic tool calls.

    Args:
        session_id: A unique identifier for this execution session.

    Returns:
        A :class:`~ledger.interceptor.LedgerSession` context manager.
        On exit, ``session.actions`` holds every captured
        :class:`~ledger.interceptor.Action`.
    """
    return LedgerSession(session_id)


__all__ = ["session", "LedgerSession"]
