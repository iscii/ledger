"""
tests/test_cli.py
~~~~~~~~~~~~~~~~~
Tests for the backstep CLI (Stage 4).

Uses Click's CliRunner so every test runs in-process — no subprocess
overhead, full access to the global registries, and clean isolation via
tmp_path fixtures.
"""

from __future__ import annotations

import os

import pytest
from click.testing import CliRunner

from backstep.cli import cli
from backstep.interceptor import Action
from backstep.store import BackstepStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed(db_path: str, session_id: str, tools: list[dict]) -> list[Action]:
    """Write a sequence of Actions into *db_path* and return them."""
    store = BackstepStore(db_path)
    actions = []
    for i, t in enumerate(tools, start=1):
        a = Action(
            session_id=session_id,
            seq=i,
            tool=t["tool"],
            args=t.get("args", {}),
            result=t.get("result", {"content": "ok"}),
            reversible=t.get("reversible", True),
            status=t.get("status", "ok"),
        )
        store.write(a)
        actions.append(a)
    store.close()
    return actions


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

class TestSessionsCommand:

    def test_sessions_empty(self, tmp_path):
        db = str(tmp_path / "test.db")
        # Create an empty DB
        BackstepStore(db).close()

        result = CliRunner().invoke(cli, ["sessions", "--db", db])

        assert result.exit_code == 0
        assert "No sessions found" in result.output

    def test_sessions_lists(self, tmp_path):
        db = str(tmp_path / "test.db")
        _seed(db, "alpha-session", [
            {"tool": "list_dir", "args": {"path": "."}},
            {"tool": "read_file", "args": {"path": "f.txt"}},
        ])

        result = CliRunner().invoke(cli, ["sessions", "--db", db])

        assert result.exit_code == 0
        assert "alpha-session" in result.output
        # action count shown
        assert "2" in result.output


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

class TestShowCommand:

    def test_show(self, tmp_path):
        db = str(tmp_path / "test.db")
        _seed(db, "show-session", [
            {
                "tool": "read_file",
                "args": {"path": "config.txt"},
                "result": {"content": "debug=true"},
            },
            {
                "tool": "write_file",
                "args": {"path": "out.txt", "content": "summary"},
                "result": {"content": "ok"},
            },
        ])

        result = CliRunner().invoke(cli, ["show", "show-session", "--db", db])

        assert result.exit_code == 0
        assert "show-session" in result.output
        assert "#1" in result.output
        assert "read_file" in result.output
        assert "#2" in result.output
        assert "write_file" in result.output
        assert "config.txt" in result.output
        assert "[reversible]" in result.output

    def test_show_not_found(self, tmp_path):
        db = str(tmp_path / "test.db")
        BackstepStore(db).close()

        result = CliRunner().invoke(cli, ["show", "nonexistent", "--db", db])

        assert result.exit_code == 0
        assert "No actions found" in result.output


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------

class TestReplayCommand:

    def test_replay(self, tmp_path):
        from backstep.tool_registry import tool_registry

        db = str(tmp_path / "test.db")
        out_file = tmp_path / "replayed.txt"

        # Register a real tool function — this is what the user would do
        def write_file(path: str, content: str) -> None:
            with open(path, "w") as fh:
                fh.write(content)

        tool_registry.register("write_file_replay_test", write_file)

        _seed(db, "replay-01", [
            {
                "tool": "write_file_replay_test",
                "args": {"path": str(out_file), "content": "hello replay"},
            },
        ])

        assert not out_file.exists()

        result = CliRunner().invoke(cli, ["replay", "replay-01", "--db", db])

        assert result.exit_code == 0
        assert "✓" in result.output
        assert out_file.exists()
        assert out_file.read_text() == "hello replay"

    def test_replay_no_tool_registered(self, tmp_path):
        db = str(tmp_path / "test.db")
        _seed(db, "replay-02", [
            {"tool": "totally_unknown_tool_xyz", "args": {}},
        ])

        result = CliRunner().invoke(cli, ["replay", "replay-02", "--db", db])

        assert result.exit_code == 0
        assert "skipped" in result.output
        assert "1 skipped" in result.output


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------

class TestRollbackCommand:

    def test_rollback(self, tmp_path):
        db = str(tmp_path / "test.db")
        out_file = tmp_path / "to_rollback.txt"
        out_file.write_text("written by agent")
        assert out_file.exists()

        _seed(db, "rb-01", [
            {
                "tool": "write_file",
                "args": {"path": str(out_file)},
                "result": {"content": "ok"},
            },
        ])

        result = CliRunner().invoke(cli, ["rollback", "rb-01", "--db", db])

        assert result.exit_code == 0
        assert "✓" in result.output
        assert not out_file.exists()

    def test_rollback_skips_committed(self, tmp_path):
        from backstep.registry import registry
        registry.register_committed("send_email")

        db = str(tmp_path / "test.db")
        _seed(db, "rb-committed", [
            {
                "tool": "send_email",
                "args": {"to": "a@b.com", "body": "hi"},
                "status": "committed",
                "reversible": False,
            },
        ])

        result = CliRunner().invoke(cli, ["rollback", "rb-committed", "--db", db])

        assert result.exit_code == 0
        assert "skipped" in result.output
        assert "0 rolled back" in result.output or "1 skipped" in result.output


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

class TestDiffCommand:

    def test_diff_identical(self, tmp_path):
        db = str(tmp_path / "test.db")
        tools = [
            {"tool": "list_dir", "args": {"path": "."}},
            {"tool": "read_file", "args": {"path": "f.txt"}},
        ]
        _seed(db, "diff-a", tools)
        _seed(db, "diff-b", tools)

        result = CliRunner().invoke(cli, ["diff", "diff-a", "diff-b", "--db", db])

        assert result.exit_code == 0
        assert "= #1" in result.output
        assert "= #2" in result.output
        assert "(same)" in result.output

    def test_diff_different(self, tmp_path):
        db = str(tmp_path / "test.db")
        _seed(db, "diff-c", [
            {"tool": "read_file", "args": {"path": "a.txt"}},
            {"tool": "write_file", "args": {"path": "out.txt", "content": "x"}},
        ])
        _seed(db, "diff-d", [
            {"tool": "read_file", "args": {"path": "b.txt"}},  # same tool, different arg
        ])

        result = CliRunner().invoke(cli, ["diff", "diff-c", "diff-d", "--db", db])

        assert result.exit_code == 0
        assert "~" in result.output   # args differ for read_file
        assert "-" in result.output   # write_file only in diff-c
        assert "Legend" in result.output
