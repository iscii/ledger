"""
backstep.rollback
~~~~~~~~~~~~~~~~~
RollbackEngine — walks a session's Actions in reverse seq order and
calls each tool's registered inverse function to undo side effects.

Usage::

    from backstep.store import BackstepStore
    from backstep.registry import registry
    from backstep.rollback import RollbackEngine

    store = BackstepStore("./backstep.db")
    engine = RollbackEngine(store, registry)

    result = engine.rollback("session-01")
    print(result.rolled_back)   # list of action ids that were undone
    print(result.skipped)       # committed / no inverse registered
    print(result.errors)        # inverses that raised exceptions
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Iterator

from backstep.interceptor import Action
from backstep.registry import InverseRegistry
from backstep.store import BackstepStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result value object
# ---------------------------------------------------------------------------

@dataclass
class RollbackResult:
    """Summary returned by :meth:`RollbackEngine.rollback`."""

    session_id: str
    rolled_back: list[str] = field(default_factory=list)
    """Action ids that were successfully undone."""
    skipped: list[str] = field(default_factory=list)
    """Action ids skipped because they are committed or have no inverse."""
    errors: list[str] = field(default_factory=list)
    """Action ids whose inverse function raised an exception."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RollbackEngine:
    """Undo the side-effects of recorded Actions using registered inverses."""

    def __init__(self, store: BackstepStore, registry: InverseRegistry) -> None:
        self._store = store
        self._registry = registry

    def rollback(self, session_id: str) -> RollbackResult:
        """Roll back *every* action in *session_id* in reverse seq order."""
        actions = self._store.get_session(session_id)
        return self._apply(session_id, reversed(actions))

    def rollback_to(self, session_id: str, seq: int) -> RollbackResult:
        """Roll back only actions with seq > *seq* in reverse seq order.

        Equivalent to "undo everything after step N".
        """
        actions = self._store.get_session(session_id)
        to_undo = [a for a in actions if a.seq > seq]
        return self._apply(session_id, reversed(to_undo))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply(self, session_id: str, actions: Iterator[Action]) -> RollbackResult:
        result = RollbackResult(session_id=session_id)

        for action in actions:
            # --- committed / explicitly irreversible --------------------
            if action.status == "committed" or not action.reversible:
                warnings.warn(
                    f"Skipping committed/irreversible action {action.id} "
                    f"(tool={action.tool!r})",
                    UserWarning,
                    stacklevel=2,
                )
                result.skipped.append(action.id)
                continue

            # --- no inverse registered ----------------------------------
            inverse = self._registry.get_inverse(action.tool)
            if inverse is None:
                warnings.warn(
                    f"No inverse registered for tool {action.tool!r} "
                    f"(action {action.id}) — skipping",
                    UserWarning,
                    stacklevel=2,
                )
                result.skipped.append(action.id)
                continue

            # --- call the inverse ---------------------------------------
            try:
                inverse(action.args, action.result)
                result.rolled_back.append(action.id)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Rollback failed for action %s (tool=%r): %s",
                    action.id,
                    action.tool,
                    exc,
                )
                result.errors.append(action.id)

        return result
