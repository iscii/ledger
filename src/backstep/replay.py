"""
backstep.replay
~~~~~~~~~~~~~~~
ReplayEngine — re-executes recorded tool calls from a session without
invoking the LLM.

Usage::

    from backstep.store import BackstepStore
    from backstep.replay import ReplayEngine

    store = BackstepStore("./backstep.db")
    engine = ReplayEngine(store)

    # Replay entire session
    result = engine.replay("demo-session")

    # Replay only specific actions
    result = engine.replay("demo-session", seqs=[3, 5, 6])

    print(result.replayed)   # count of successfully replayed actions
    print(result.skipped)    # count skipped (no tool registered or not selected)
    print(result.errors)     # list of "action_id: error message" strings
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backstep.store import BackstepStore
from backstep.tool_registry import ToolRegistry, tool_registry as _default_registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result value object
# ---------------------------------------------------------------------------

@dataclass
class ReplayResult:
    """Summary returned by :meth:`ReplayEngine.replay`."""

    session_id: str
    replayed: int = 0
    """Count of actions successfully re-executed."""
    skipped: int = 0
    """Count of actions skipped (no tool registered, or not in selected seqs)."""
    errors: list[str] = field(default_factory=list)
    """'action_id: error message' strings for actions that raised exceptions."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ReplayEngine:
    """Re-execute tool calls recorded in a session."""

    def __init__(
        self,
        store: BackstepStore,
        registry: ToolRegistry | None = None,
    ) -> None:
        self._store = store
        self._registry = registry or _default_registry

    def replay(
        self,
        session_id: str,
        seqs: list[int] | None = None,
    ) -> ReplayResult:
        """Replay actions in *session_id*.

        Args:
            session_id: The session to replay.
            seqs:       Optional list of seq numbers to replay.  If ``None``
                        (default) every action is replayed.  Actions whose seq
                        is not in *seqs* are counted as skipped.

        Returns:
            :class:`ReplayResult` with counts and any error strings.
        """
        actions = self._store.get_session(session_id)
        result = ReplayResult(session_id=session_id)

        for action in actions:
            # Skip actions not in the requested set
            if seqs is not None and action.seq not in seqs:
                result.skipped += 1
                continue

            fn = self._registry.get(action.tool)
            if fn is None:
                logger.debug("No tool registered for %r — skipping #%d", action.tool, action.seq)
                result.skipped += 1
                continue

            try:
                fn(**action.args)
                result.replayed += 1
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Replay failed for action %s (tool=%r, seq=%d): %s",
                    action.id,
                    action.tool,
                    action.seq,
                    exc,
                )
                result.errors.append(f"{action.id}: {exc}")

        return result
