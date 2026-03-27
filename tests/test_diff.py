"""
tests/test_diff.py
~~~~~~~~~~~~~~~~~~
Tests for backstep.diff.DiffEngine.
"""

from __future__ import annotations

import pytest

from backstep.diff import DiffEngine, DiffResult, ActionDiff
from backstep.interceptor import Action
from backstep.store import BackstepStore


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _seed(store: BackstepStore, session_id: str, specs: list[dict]) -> list[Action]:
    actions = []
    for i, s in enumerate(specs, start=1):
        a = Action(
            session_id=session_id,
            seq=i,
            tool=s["tool"],
            args=s.get("args", {}),
            result=s.get("result", {"content": "ok"}),
        )
        store.write(a)
        actions.append(a)
    return actions


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDiffIdentical:
    def test_all_same_is_identical(self, tmp_path):
        store = BackstepStore(str(tmp_path / "test.db"))
        specs = [
            {"tool": "list_dir",  "args": {"path": "."}, "result": {"content": "f.txt"}},
            {"tool": "read_file", "args": {"path": "f.txt"}, "result": {"content": "hello"}},
        ]
        _seed(store, "a", specs)
        _seed(store, "b", specs)

        engine = DiffEngine(store)
        result = engine.diff("a", "b")

        assert result.is_identical
        assert len(result.same) == 2
        assert result.changed == []
        assert result.added == []
        assert result.removed == []
        store.close()


class TestDiffArgsChanged:
    def test_changed_entry_and_changes_dict(self, tmp_path):
        store = BackstepStore(str(tmp_path / "test.db"))
        _seed(store, "a", [
            {"tool": "list_dir",  "args": {"path": "."}},
            {"tool": "read_file", "args": {"path": "a.txt"}, "result": {"content": "aaa"}},
            {"tool": "list_dir",  "args": {"path": "."}},
        ])
        _seed(store, "b", [
            {"tool": "list_dir",  "args": {"path": "."}},
            {"tool": "read_file", "args": {"path": "b.txt"}, "result": {"content": "bbb"}},
            {"tool": "list_dir",  "args": {"path": "."}},
        ])

        engine = DiffEngine(store)
        result = engine.diff("a", "b")

        assert not result.is_identical
        assert len(result.same) == 2
        assert len(result.changed) == 1

        changed = result.changed[0]
        assert changed.seq == 2
        assert changed.tool == "read_file"
        assert "args" in changed.changes
        assert changed.changes["args"]["from"] == {"path": "a.txt"}
        assert changed.changes["args"]["to"]   == {"path": "b.txt"}
        assert "result" in changed.changes
        store.close()


class TestDiffAdded:
    def test_extra_action_in_b_is_added(self, tmp_path):
        store = BackstepStore(str(tmp_path / "test.db"))
        _seed(store, "a", [
            {"tool": "read_file", "args": {"path": "f.txt"}},
        ])
        _seed(store, "b", [
            {"tool": "read_file", "args": {"path": "f.txt"}},
            {"tool": "write_file", "args": {"path": "out.txt", "content": "x"}},
        ])

        engine = DiffEngine(store)
        result = engine.diff("a", "b")

        assert len(result.added) == 1
        assert result.added[0].tool == "write_file"
        assert result.added[0].action_a is None
        assert result.added[0].action_b is not None
        store.close()


class TestDiffRemoved:
    def test_extra_action_in_a_is_removed(self, tmp_path):
        store = BackstepStore(str(tmp_path / "test.db"))
        _seed(store, "a", [
            {"tool": "read_file",  "args": {"path": "f.txt"}},
            {"tool": "write_file", "args": {"path": "out.txt", "content": "x"}},
        ])
        _seed(store, "b", [
            {"tool": "read_file", "args": {"path": "f.txt"}},
        ])

        engine = DiffEngine(store)
        result = engine.diff("a", "b")

        assert len(result.removed) == 1
        assert result.removed[0].tool == "write_file"
        assert result.removed[0].action_b is None
        assert result.removed[0].action_a is not None
        store.close()


class TestDiffToolSwap:
    def test_different_tools_at_same_seq_produces_removed_and_added(self, tmp_path):
        store = BackstepStore(str(tmp_path / "test.db"))
        _seed(store, "a", [
            {"tool": "read_file",   "args": {"path": "f.txt"}},
            {"tool": "write_file",  "args": {"path": "out.txt", "content": "x"}},
        ])
        _seed(store, "b", [
            {"tool": "read_file",   "args": {"path": "f.txt"}},
            {"tool": "delete_file", "args": {"path": "out.txt"}},
        ])

        engine = DiffEngine(store)
        result = engine.diff("a", "b")

        kinds = [d.kind for d in result.actions]
        assert "removed" in kinds
        assert "added"   in kinds
        removed = [d for d in result.actions if d.kind == "removed"]
        added   = [d for d in result.actions if d.kind == "added"]
        assert removed[0].tool == "write_file"
        assert added[0].tool   == "delete_file"
        store.close()


class TestDiffEmptySessions:
    def test_both_empty_is_identical(self, tmp_path):
        store = BackstepStore(str(tmp_path / "test.db"))
        # Sessions exist in the store with no actions — we seed nothing
        # DiffEngine works on action lists, so empty → empty comparison
        engine = DiffEngine(store)
        result = engine.diff("empty-a", "empty-b")

        assert result.actions == []
        assert result.is_identical
        store.close()
