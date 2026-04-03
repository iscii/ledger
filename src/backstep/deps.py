"""
backstep.deps
~~~~~~~~~~~~~
DependencyAnalyzer — detects dependency violations when a selective
subset of actions is chosen for replay or rollback.

Dependency detection uses path-based heuristics only:
  - An action "writes" a path if its tool is a write-type tool and
    one of its string args looks like a file path.
  - An action "depends on" a prior action if both reference the same
    path and the prior action was the first to write it in the session.

blocking=True  — structural dependency (file created from scratch by
                 a prior action that is not selected).
blocking=False — incidental dependency (same path touched, but the
                 file existed before the session or was modified, not
                 created).

Usage::

    from backstep.deps import DependencyAnalyzer

    analyzer = DependencyAnalyzer(actions)

    violations = analyzer.check_replay([3, 5])
    for v in violations:
        print(v.blocking, v.reason)

    violations = analyzer.check_rollback([1, 2])
"""

from __future__ import annotations

from dataclasses import dataclass

from backstep.interceptor import Action

# Tools that create or overwrite a file (structural writes)
_WRITE_TOOLS: frozenset[str] = frozenset(
    {"write_file", "create_file", "copy_file", "move_file"}
)

# Tools that modify without full creation (incidental writes)
_MODIFY_TOOLS: frozenset[str] = frozenset({"append_file", "patch_file"})

# All tools that produce side-effects on paths
_ALL_WRITE_TOOLS: frozenset[str] = _WRITE_TOOLS | _MODIFY_TOOLS


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass
class DependencyViolation:
    """A dependency relationship that may be violated by a selective operation."""

    action_seq: int
    """The seq of the action being targeted (selected for replay/rollback)."""

    depends_on_seq: int
    """The seq of the action it depends on (or that depends on it)."""

    tool: str
    """Tool name of the targeted action."""

    reason: str
    """Human-readable explanation of the dependency."""

    blocking: bool
    """True = halt execution.  False = warn only (--force bypasses)."""


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class DependencyAnalyzer:
    """Detect dependency violations in a selective replay or rollback."""

    def __init__(self, actions: list[Action]) -> None:
        self._actions = sorted(actions, key=lambda a: a.seq)

        # Map path -> seq of first write in this session (structural creator)
        self._first_writer: dict[str, int] = {}
        for action in self._actions:
            if action.tool in _WRITE_TOOLS:
                for path in self._extract_paths(action):
                    if path not in self._first_writer:
                        self._first_writer[path] = action.seq

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_replay(self, selected_seqs: list[int]) -> list[DependencyViolation]:
        """Check whether any selected action depends on a non-selected prior action.

        For each selected action B, look for earlier actions A (not selected)
        that write a path B also references.  If A was the *first* writer of
        that path in the session the dependency is structural (blocking=True).
        """
        selected = set(selected_seqs)
        violations: list[DependencyViolation] = []

        for action in self._actions:
            if action.seq not in selected:
                continue

            paths = self._extract_paths(action)

            for earlier in self._actions:
                if earlier.seq >= action.seq:
                    break
                if earlier.seq in selected:
                    continue
                if earlier.tool not in _ALL_WRITE_TOOLS:
                    continue

                shared = paths & self._extract_paths(earlier)
                if not shared:
                    continue

                for path in shared:
                    blocking = self._first_writer.get(path) == earlier.seq
                    violations.append(DependencyViolation(
                        action_seq=action.seq,
                        depends_on_seq=earlier.seq,
                        tool=action.tool,
                        reason=(
                            f"#{earlier.seq} ({earlier.tool}) "
                            f"{'created' if blocking else 'modified'} "
                            f"{path!r} which #{action.seq} ({action.tool}) uses"
                        ),
                        blocking=blocking,
                    ))

        return violations

    def check_rollback(self, selected_seqs: list[int]) -> list[DependencyViolation]:
        """Check whether rolling back selected actions would orphan later non-selected ones.

        For each selected action A being rolled back, look for later actions B
        (not selected) that reference the same path.  If A was the first writer
        of that path, rolling it back deletes the file — making B inconsistent
        (blocking=True).
        """
        selected = set(selected_seqs)
        violations: list[DependencyViolation] = []

        for action in self._actions:
            if action.seq not in selected:
                continue
            if action.tool not in _ALL_WRITE_TOOLS:
                continue

            paths = self._extract_paths(action)

            for later in self._actions:
                if later.seq <= action.seq:
                    continue
                if later.seq in selected:
                    continue

                shared = paths & self._extract_paths(later)
                if not shared:
                    continue

                for path in shared:
                    blocking = self._first_writer.get(path) == action.seq
                    violations.append(DependencyViolation(
                        action_seq=action.seq,
                        depends_on_seq=later.seq,
                        tool=action.tool,
                        reason=(
                            f"Rolling back #{action.seq} ({action.tool}) would "
                            f"{'delete' if blocking else 'modify'} {path!r}, "
                            f"which #{later.seq} ({later.tool}) still depends on"
                        ),
                        blocking=blocking,
                    ))

        return violations

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_paths(self, action: Action) -> set[str]:
        """Return all string arg values that look like file paths."""
        paths: set[str] = set()
        for v in action.args.values():
            if isinstance(v, str) and _looks_like_path(v):
                paths.add(v)
        return paths


def _looks_like_path(s: str) -> bool:
    """Heuristic: does this string look like a filesystem path?"""
    if not s or len(s) > 512:
        return False
    if "/" in s or "\\" in s:
        return True
    # Has a non-leading dot that could be an extension
    if "." in s[1:]:
        ext = s.rsplit(".", 1)[1]
        if 1 <= len(ext) <= 6 and ext.isalpha():
            return True
    return False
