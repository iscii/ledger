"""
backstep.diff
~~~~~~~~~~~~~
DiffEngine — compares two recorded sessions action by action and returns
a structured DiffResult.

Algorithm
---------
Actions are matched by sequence number.  For each seq position:

  Both sessions have an action at seq N:
    - tool, args, result all match          → "same"
    - tool matches, args or result differ   → "changed" (changes dict populated)
    - tools differ                          → "removed" (from A) + "added" (from B)

  Only session A has action at seq N        → "removed"
  Only session B has action at seq N        → "added"

Usage::

    from backstep.store import BackstepStore
    from backstep.diff import DiffEngine

    store = BackstepStore("./backstep.db")
    engine = DiffEngine(store)
    result = engine.diff("session-a", "session-b")

    print(result.is_identical)          # True / False
    for d in result.changed:
        print(d.seq, d.changes)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from backstep.interceptor import Action
from backstep.store import BackstepStore


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass
class ActionDiff:
    """Diff entry for a single seq position."""

    kind: Literal["same", "changed", "added", "removed"]
    seq: int
    tool: str
    action_a: Action | None  # None when kind == "added"
    action_b: Action | None  # None when kind == "removed"
    changes: dict = field(default_factory=dict)
    """Field-level diff populated when kind == "changed".

    Structure::

        {
            "args":   {"from": {...}, "to": {...}},
            "result": {"from": {...}, "to": {...}},
        }
    """


@dataclass
class DiffResult:
    """Structured comparison of two sessions."""

    session_a: str
    session_b: str
    actions: list[ActionDiff] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience filters
    # ------------------------------------------------------------------

    @property
    def same(self) -> list[ActionDiff]:
        return [d for d in self.actions if d.kind == "same"]

    @property
    def changed(self) -> list[ActionDiff]:
        return [d for d in self.actions if d.kind == "changed"]

    @property
    def added(self) -> list[ActionDiff]:
        return [d for d in self.actions if d.kind == "added"]

    @property
    def removed(self) -> list[ActionDiff]:
        return [d for d in self.actions if d.kind == "removed"]

    @property
    def is_identical(self) -> bool:
        """True when every entry is "same" (or both sessions are empty)."""
        return all(d.kind == "same" for d in self.actions)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class DiffEngine:
    """Compare two sessions stored in a :class:`~backstep.store.BackstepStore`."""

    def __init__(self, store: BackstepStore) -> None:
        self._store = store

    def diff(self, session_a: str, session_b: str) -> DiffResult:
        """Return a :class:`DiffResult` comparing *session_a* and *session_b*."""
        actions_a = self._store.get_session(session_a)
        actions_b = self._store.get_session(session_b)
        return _compare(session_a, session_b, actions_a, actions_b)


# ---------------------------------------------------------------------------
# Internal comparison logic
# ---------------------------------------------------------------------------

def _compare(
    session_a: str,
    session_b: str,
    actions_a: list[Action],
    actions_b: list[Action],
) -> DiffResult:
    result = DiffResult(session_a=session_a, session_b=session_b)
    max_len = max(len(actions_a), len(actions_b), 0)

    for i in range(max_len):
        a = actions_a[i] if i < len(actions_a) else None
        b = actions_b[i] if i < len(actions_b) else None

        if a is not None and b is not None:
            if a.tool != b.tool:
                # Different tools at same position: removed from A, added in B
                result.actions.append(ActionDiff(
                    kind="removed",
                    seq=a.seq,
                    tool=a.tool,
                    action_a=a,
                    action_b=None,
                ))
                result.actions.append(ActionDiff(
                    kind="added",
                    seq=b.seq,
                    tool=b.tool,
                    action_a=None,
                    action_b=b,
                ))
            elif a.args == b.args and a.result == b.result:
                result.actions.append(ActionDiff(
                    kind="same",
                    seq=a.seq,
                    tool=a.tool,
                    action_a=a,
                    action_b=b,
                ))
            else:
                changes: dict = {}
                if a.args != b.args:
                    changes["args"] = {"from": a.args, "to": b.args}
                if a.result != b.result:
                    changes["result"] = {"from": a.result, "to": b.result}
                result.actions.append(ActionDiff(
                    kind="changed",
                    seq=a.seq,
                    tool=a.tool,
                    action_a=a,
                    action_b=b,
                    changes=changes,
                ))

        elif a is not None:
            result.actions.append(ActionDiff(
                kind="removed",
                seq=a.seq,
                tool=a.tool,
                action_a=a,
                action_b=None,
            ))
        else:
            assert b is not None
            result.actions.append(ActionDiff(
                kind="added",
                seq=b.seq,
                tool=b.tool,
                action_a=None,
                action_b=b,
            ))

    return result
