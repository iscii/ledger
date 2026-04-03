"""
tests/test_selective.py
~~~~~~~~~~~~~~~~~~~~~~~
Tests for selective replay, selective rollback, dependency analysis,
and rollback feasibility checking.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from backstep.cli import cli
from backstep.deps import DependencyAnalyzer, DependencyViolation
from backstep.interceptor import Action
from backstep.registry import InverseRegistry
from backstep.replay import ReplayEngine, ReplayResult
from backstep.rollback import RollbackEngine, FeasibilityResult
from backstep.store import BackstepStore
from backstep.tool_registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_action(session_id: str, seq: int, tool: str, args: dict, **kw) -> Action:
    return Action(
        session_id=session_id,
        seq=seq,
        tool=tool,
        args=args,
        result=kw.get("result", {"ok": True}),
        reversible=kw.get("reversible", True),
        status=kw.get("status", "ok"),
    )


def _seed(db_path: str, session_id: str, specs: list[dict]) -> list[Action]:
    store = BackstepStore(db_path)
    actions = []
    for i, spec in enumerate(specs, start=1):
        a = _make_action(
            session_id=session_id,
            seq=i,
            tool=spec["tool"],
            args=spec.get("args", {}),
            result=spec.get("result", {"ok": True}),
            reversible=spec.get("reversible", True),
            status=spec.get("status", "ok"),
        )
        store.write(a)
        actions.append(a)
    store.close()
    return actions


# ---------------------------------------------------------------------------
# ReplayEngine — selective replay
# ---------------------------------------------------------------------------

class TestReplaySpecificSeqs:

    def test_replay_specific_seqs(self, tmp_path):
        db = str(tmp_path / "test.db")
        replayed_tools: list[str] = []

        registry = ToolRegistry()
        registry.register("list_dir",  lambda path: replayed_tools.append("list_dir"))
        registry.register("read_file", lambda path: replayed_tools.append("read_file"))
        registry.register("write_file",lambda path, content: replayed_tools.append("write_file"))

        _seed(db, "s1", [
            {"tool": "list_dir",   "args": {"path": "/tmp"}},
            {"tool": "read_file",  "args": {"path": "/tmp/a.txt"}},
            {"tool": "write_file", "args": {"path": "/tmp/b.txt", "content": "x"}},
        ])

        store = BackstepStore(db)
        engine = ReplayEngine(store, registry)
        result = engine.replay("s1", seqs=[1, 3])
        store.close()

        assert result.replayed == 2
        assert result.skipped == 1
        assert result.errors == []
        assert replayed_tools == ["list_dir", "write_file"]

    def test_replay_all_when_seqs_none(self, tmp_path):
        db = str(tmp_path / "test.db")
        call_count: list[int] = [0]

        registry = ToolRegistry()
        registry.register("read_file", lambda path: call_count.__setitem__(0, call_count[0] + 1))

        _seed(db, "s1", [
            {"tool": "read_file", "args": {"path": "/tmp/a.txt"}},
            {"tool": "read_file", "args": {"path": "/tmp/b.txt"}},
        ])

        store = BackstepStore(db)
        engine = ReplayEngine(store, registry)
        result = engine.replay("s1", seqs=None)
        store.close()

        assert result.replayed == 2
        assert call_count[0] == 2

    def test_replay_from(self, tmp_path):
        """--from N replays seqs N and above."""
        db = str(tmp_path / "test.db")
        replayed: list[int] = []

        registry = ToolRegistry()
        for tool in ("a", "b", "c", "d"):
            t = tool  # capture
            registry.register(t, lambda seq=t: replayed.append(seq))

        _seed(db, "s1", [
            {"tool": "a", "args": {}},
            {"tool": "b", "args": {}},
            {"tool": "c", "args": {}},
            {"tool": "d", "args": {}},
        ])

        store = BackstepStore(db)
        engine = ReplayEngine(store, registry)
        result = engine.replay("s1", seqs=[3, 4])
        store.close()

        assert result.replayed == 2
        assert result.skipped == 2

    def test_replay_range(self, tmp_path):
        """Seqs [2,3] replays only those two."""
        db = str(tmp_path / "test.db")
        hit: list[int] = []

        registry = ToolRegistry()
        for i in range(1, 5):
            seq = i
            registry.register(f"tool{i}", lambda s=seq: hit.append(s))

        _seed(db, "s1", [{"tool": f"tool{i}", "args": {}} for i in range(1, 5)])

        store = BackstepStore(db)
        engine = ReplayEngine(store, registry)
        result = engine.replay("s1", seqs=[2, 3])
        store.close()

        assert result.replayed == 2
        assert result.skipped == 2

    def test_replay_seq_and_range_error(self, tmp_path):
        """CLI should error if --seq and --from/--to are both provided."""
        db = str(tmp_path / "test.db")
        _seed(db, "s1", [{"tool": "read_file", "args": {"path": "/x"}}])

        result = CliRunner().invoke(
            cli,
            ["replay", "s1", "--db", db, "--seq", "1", "--from", "1"],
        )
        assert result.exit_code != 0
        assert "not both" in result.output


# ---------------------------------------------------------------------------
# RollbackEngine — selective rollback
# ---------------------------------------------------------------------------

class TestRollbackSpecificSeqs:

    def test_rollback_specific_seqs(self, tmp_path):
        db = str(tmp_path / "test.db")
        undone: list[int] = []

        reg = InverseRegistry()
        reg.register("write_file", lambda args, result: undone.append(args["seq"]))

        _seed(db, "s1", [
            {"tool": "write_file", "args": {"seq": 1, "path": "/a"}},
            {"tool": "write_file", "args": {"seq": 2, "path": "/b"}},
            {"tool": "write_file", "args": {"seq": 3, "path": "/c"}},
        ])

        store = BackstepStore(db)
        engine = RollbackEngine(store, reg)
        result = engine.rollback("s1", seqs=[1, 3])
        store.close()

        assert len(result.rolled_back) == 2
        assert len(result.skipped) == 0
        # rolled back in reverse order (3 then 1)
        assert 3 in undone and 1 in undone
        assert 2 not in undone

    def test_rollback_all_when_seqs_none(self, tmp_path):
        db = str(tmp_path / "test.db")
        undone: list[int] = []

        reg = InverseRegistry()
        reg.register("write_file", lambda args, result: undone.append(args["seq"]))

        _seed(db, "s1", [
            {"tool": "write_file", "args": {"seq": i, "path": f"/{i}"}}
            for i in range(1, 4)
        ])

        store = BackstepStore(db)
        engine = RollbackEngine(store, reg)
        result = engine.rollback("s1", seqs=None)
        store.close()

        assert len(result.rolled_back) == 3

    def test_rollback_from(self, tmp_path):
        """seqs=[2,3] should roll back only those actions."""
        db = str(tmp_path / "test.db")
        undone: list[int] = []

        reg = InverseRegistry()
        reg.register("write_file", lambda args, result: undone.append(args["seq"]))

        _seed(db, "s1", [
            {"tool": "write_file", "args": {"seq": i, "path": f"/{i}"}}
            for i in range(1, 4)
        ])

        store = BackstepStore(db)
        engine = RollbackEngine(store, reg)
        result = engine.rollback("s1", seqs=[2, 3])
        store.close()

        assert len(result.rolled_back) == 2
        assert 1 not in undone
        assert 2 in undone and 3 in undone

    def test_rollback_feasibility(self, tmp_path):
        db = str(tmp_path / "test.db")

        reg = InverseRegistry()
        reg.register("write_file", lambda args, result: None)

        _seed(db, "s1", [
            {"tool": "write_file", "args": {"path": "/a"}},
            {"tool": "read_file",  "args": {"path": "/a"}},
            {"tool": "write_file", "args": {"path": "/b"}, "status": "committed"},
        ])

        store = BackstepStore(db)
        engine = RollbackEngine(store, reg)
        result = engine.can_rollback("s1")
        store.close()

        assert isinstance(result, FeasibilityResult)
        # seq 1 has inverse → can rollback
        assert 1 in result.actions_that_can_rollback
        # seq 2 read_file → no inverse
        assert 2 in result.actions_that_cannot
        # seq 3 committed → cannot
        assert 3 in result.actions_that_cannot
        assert 3 in result.blocking_committed
        assert result.feasible is True

    def test_rollback_feasibility_selective(self, tmp_path):
        db = str(tmp_path / "test.db")

        reg = InverseRegistry()
        reg.register("write_file", lambda args, result: None)

        _seed(db, "s1", [
            {"tool": "write_file", "args": {"path": "/a"}},
            {"tool": "write_file", "args": {"path": "/b"}},
            {"tool": "write_file", "args": {"path": "/c"}},
        ])

        store = BackstepStore(db)
        engine = RollbackEngine(store, reg)
        result = engine.can_rollback("s1", seqs=[2])
        store.close()

        # Only seq 2 should be in the report
        assert len(result.actions) == 1
        assert result.actions[0].seq == 2
        assert result.feasible is True


# ---------------------------------------------------------------------------
# DependencyAnalyzer
# ---------------------------------------------------------------------------

class TestDependencyAnalyzer:

    def _actions(self, specs: list[dict]) -> list[Action]:
        return [
            _make_action("s", i + 1, s["tool"], s.get("args", {}))
            for i, s in enumerate(specs)
        ]

    def test_dep_replay_missing_creator(self):
        """Blocking violation: replay action that needs a file not being created."""
        actions = self._actions([
            {"tool": "write_file", "args": {"path": "/tmp/config.txt", "content": "x"}},
            {"tool": "read_file",  "args": {"path": "/tmp/config.txt"}},
        ])
        analyzer = DependencyAnalyzer(actions)
        violations = analyzer.check_replay(selected_seqs=[2])  # replay #2 but not #1

        assert len(violations) == 1
        v = violations[0]
        assert v.action_seq == 2
        assert v.depends_on_seq == 1
        assert v.blocking is True

    def test_dep_replay_no_violation(self):
        """No violation when all deps are included in selection."""
        actions = self._actions([
            {"tool": "write_file", "args": {"path": "/tmp/config.txt", "content": "x"}},
            {"tool": "read_file",  "args": {"path": "/tmp/config.txt"}},
        ])
        analyzer = DependencyAnalyzer(actions)
        violations = analyzer.check_replay(selected_seqs=[1, 2])

        assert violations == []

    def test_dep_replay_no_violation_unrelated(self):
        """No violation when actions don't share paths."""
        actions = self._actions([
            {"tool": "write_file", "args": {"path": "/tmp/a.txt", "content": "x"}},
            {"tool": "read_file",  "args": {"path": "/tmp/b.txt"}},
        ])
        analyzer = DependencyAnalyzer(actions)
        violations = analyzer.check_replay(selected_seqs=[2])

        assert violations == []

    def test_dep_rollback_orphans_later(self):
        """Blocking violation: rolling back creator while later dependent is kept."""
        actions = self._actions([
            {"tool": "write_file", "args": {"path": "/tmp/config.txt", "content": "x"}},
            {"tool": "read_file",  "args": {"path": "/tmp/config.txt"}},
        ])
        analyzer = DependencyAnalyzer(actions)
        # Roll back #1 (creator) but not #2 (reader)
        violations = analyzer.check_rollback(selected_seqs=[1])

        assert len(violations) == 1
        v = violations[0]
        assert v.action_seq == 1
        assert v.depends_on_seq == 2
        assert v.blocking is True

    def test_dep_rollback_no_violation(self):
        """No violation when rolling back both creator and dependent."""
        actions = self._actions([
            {"tool": "write_file", "args": {"path": "/tmp/config.txt", "content": "x"}},
            {"tool": "read_file",  "args": {"path": "/tmp/config.txt"}},
        ])
        analyzer = DependencyAnalyzer(actions)
        violations = analyzer.check_rollback(selected_seqs=[1, 2])

        assert violations == []

    def test_dep_rollback_no_violation_no_later(self):
        """No violation rolling back the last action in the session."""
        actions = self._actions([
            {"tool": "write_file", "args": {"path": "/tmp/a.txt", "content": "x"}},
            {"tool": "write_file", "args": {"path": "/tmp/b.txt", "content": "y"}},
        ])
        analyzer = DependencyAnalyzer(actions)
        violations = analyzer.check_rollback(selected_seqs=[2])

        assert violations == []

    def test_dep_non_blocking_modify(self):
        """A second write to same path is non-blocking (not first creator)."""
        actions = self._actions([
            {"tool": "write_file",  "args": {"path": "/tmp/x.txt", "content": "a"}},
            {"tool": "append_file", "args": {"path": "/tmp/x.txt", "content": "b"}},
            {"tool": "read_file",   "args": {"path": "/tmp/x.txt"}},
        ])
        analyzer = DependencyAnalyzer(actions)
        # Replay #3 without #2 (modifier, not creator)
        violations = analyzer.check_replay(selected_seqs=[1, 3])

        # #2 is not selected and modifies the path — non-blocking
        blocking = [v for v in violations if v.blocking]
        assert blocking == []


# ---------------------------------------------------------------------------
# CLI — selective flags
# ---------------------------------------------------------------------------

class TestCLISelectiveFlags:

    def test_cli_replay_seq_flag(self, tmp_path):
        db = str(tmp_path / "test.db")
        _seed(db, "s1", [
            {"tool": "read_file", "args": {"path": "/a"}},
            {"tool": "read_file", "args": {"path": "/b"}},
            {"tool": "read_file", "args": {"path": "/c"}},
        ])
        result = CliRunner().invoke(
            cli, ["replay", "s1", "--db", db, "--seq", "2"]
        )
        assert result.exit_code == 0
        assert "1 replayed" in result.output or "skipped" in result.output

    def test_cli_rollback_yes_flag(self, tmp_path):
        db = str(tmp_path / "test.db")
        _seed(db, "s1", [
            {"tool": "read_file", "args": {"path": "/a"}},
        ])
        result = CliRunner().invoke(
            cli, ["rollback", "s1", "--db", db, "--yes"]
        )
        # Should not prompt for confirmation and should complete
        assert result.exit_code == 0
        assert "Proceed?" not in result.output

    def test_cli_rollback_from_flag(self, tmp_path):
        db = str(tmp_path / "test.db")
        _seed(db, "s1", [
            {"tool": "read_file", "args": {"path": "/a"}},
            {"tool": "read_file", "args": {"path": "/b"}},
            {"tool": "read_file", "args": {"path": "/c"}},
        ])
        result = CliRunner().invoke(
            cli, ["rollback", "s1", "--db", db, "--from", "2", "--yes"]
        )
        assert result.exit_code == 0
        # Actions 2 and 3 targeted; read_file has no inverse so they're skipped
        assert "will be skipped" in result.output

    def test_cli_replay_conflict_error(self, tmp_path):
        db = str(tmp_path / "test.db")
        _seed(db, "s1", [{"tool": "read_file", "args": {"path": "/a"}}])

        result = CliRunner().invoke(
            cli,
            ["replay", "s1", "--db", db, "--seq", "1", "--from", "1"],
        )
        assert result.exit_code != 0
        assert "not both" in result.output

    def test_cli_rollback_conflict_error(self, tmp_path):
        db = str(tmp_path / "test.db")
        _seed(db, "s1", [{"tool": "read_file", "args": {"path": "/a"}}])

        result = CliRunner().invoke(
            cli,
            ["rollback", "s1", "--db", db, "--seq", "1", "--to", "1", "--yes"],
        )
        assert result.exit_code != 0
        assert "not both" in result.output

    def test_cli_force_bypasses_warning(self, tmp_path):
        """--force proceeds despite non-blocking warnings.

        Setup: #1 creates /tmp/x.txt, #2 appends to it, #3 reads it.
        Selecting #1 and #3 (skipping #2 the modifier) produces a
        non-blocking warning because #2 is not the file creator.
        --force should allow replay to proceed without aborting.
        """
        db = str(tmp_path / "test.db")
        _seed(db, "s1", [
            {"tool": "write_file",  "args": {"path": "/tmp/x.txt", "content": "a"}},
            {"tool": "append_file", "args": {"path": "/tmp/x.txt", "content": "b"}},
            {"tool": "read_file",   "args": {"path": "/tmp/x.txt"}},
        ])
        # Replay #1 and #3, skipping #2 (append_file — non-blocking modifier)
        result = CliRunner().invoke(
            cli,
            ["replay", "s1", "--db", db, "--seq", "1", "--seq", "3", "--force"],
        )
        # --force suppresses the non-blocking warning; no hard error
        assert "Error: cannot safely" not in result.output
