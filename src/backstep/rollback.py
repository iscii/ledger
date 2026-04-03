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

    # Roll back entire session
    result = engine.rollback("session-01")

    # Roll back only specific actions
    result = engine.rollback("session-01", seqs=[4, 5, 6])

    print(result.rolled_back)   # list of action ids that were undone
    print(result.skipped)       # committed / no inverse registered
    print(result.errors)        # inverses that raised exceptions

    # Check feasibility before rolling back
    feasibility = engine.can_rollback("session-01")
    print(feasibility.feasible)
    print(feasibility.actions_that_can_rollback)  # seq numbers
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
# Result value objects
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


@dataclass
class ActionFeasibility:
    """Per-action feasibility detail."""

    seq: int
    tool: str
    can_rollback: bool
    reason: str
    """Why this action can or cannot be rolled back."""


@dataclass
class FeasibilityResult:
    """Returned by :meth:`RollbackEngine.can_rollback`."""

    session_id: str
    feasible: bool
    """True if at least one action can be rolled back."""

    actions: list[ActionFeasibility] = field(default_factory=list)
    """Per-action details in reverse seq order (as rollback would process them)."""

    actions_that_can_rollback: list[int] = field(default_factory=list)
    """Seq numbers of actions that have a registered inverse."""

    actions_that_cannot: list[int] = field(default_factory=list)
    """Seq numbers of actions that are committed, irreversible, or have no inverse."""

    blocking_committed: list[int] = field(default_factory=list)
    """Committed action seq numbers within the selected range."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RollbackEngine:
    """Undo the side-effects of recorded Actions using registered inverses."""

    def __init__(self, store: BackstepStore, registry: InverseRegistry) -> None:
        self._store = store
        self._registry = registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rollback(
        self,
        session_id: str,
        seqs: list[int] | None = None,
    ) -> RollbackResult:
        """Roll back actions in *session_id* in reverse seq order.

        Args:
            session_id: The session to roll back.
            seqs:       Optional list of seq numbers to target.  If ``None``
                        (default) every action is processed.  Actions whose
                        seq is not in *seqs* are silently skipped.

        Returns:
            :class:`RollbackResult` with ids of rolled-back, skipped, and
            errored actions.
        """
        actions = self._store.get_session(session_id)
        if seqs is not None:
            actions = [a for a in actions if a.seq in seqs]
        return self._apply(session_id, reversed(actions))

    def rollback_to(self, session_id: str, seq: int) -> RollbackResult:
        """Roll back only actions with seq > *seq* in reverse seq order.

        Equivalent to "undo everything after step N".
        """
        actions = self._store.get_session(session_id)
        to_undo = [a for a in actions if a.seq > seq]
        return self._apply(session_id, reversed(to_undo))

    def can_rollback(
        self,
        session_id: str,
        seqs: list[int] | None = None,
    ) -> FeasibilityResult:
        """Return a feasibility report for rolling back *session_id*.

        Args:
            session_id: The session to inspect.
            seqs:       Optional seq filter — only inspect these actions.

        Returns:
            :class:`FeasibilityResult` with per-action rollback status.
        """
        all_actions = self._store.get_session(session_id)
        target = [a for a in all_actions if a.seq in seqs] if seqs is not None else all_actions

        can: list[int] = []
        cannot: list[int] = []
        committed_blocking: list[int] = []
        details: list[ActionFeasibility] = []

        for action in reversed(target):
            if action.status == "committed":
                cannot.append(action.seq)
                committed_blocking.append(action.seq)
                details.append(ActionFeasibility(
                    seq=action.seq,
                    tool=action.tool,
                    can_rollback=False,
                    reason="committed — cannot be undone",
                ))
            elif not action.reversible:
                cannot.append(action.seq)
                details.append(ActionFeasibility(
                    seq=action.seq,
                    tool=action.tool,
                    can_rollback=False,
                    reason="marked irreversible",
                ))
            elif self._registry.get_inverse(action.tool) is None:
                cannot.append(action.seq)
                details.append(ActionFeasibility(
                    seq=action.seq,
                    tool=action.tool,
                    can_rollback=False,
                    reason="no inverse registered — read-only, will skip",
                ))
            else:
                can.append(action.seq)
                inverse_fn = self._registry.get_inverse(action.tool)
                inverse_name = getattr(inverse_fn, "__name__", "inverse")
                details.append(ActionFeasibility(
                    seq=action.seq,
                    tool=action.tool,
                    can_rollback=True,
                    reason=f"inverse registered ({inverse_name})",
                ))

        return FeasibilityResult(
            session_id=session_id,
            feasible=bool(can),
            actions=details,
            actions_that_can_rollback=can,
            actions_that_cannot=cannot,
            blocking_committed=committed_blocking,
        )

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
