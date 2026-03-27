"""
tests/test_stress.py
~~~~~~~~~~~~~~~~~~~~
Rollback reliability stress tests and plugin loading verification.
"""

from __future__ import annotations

import os
import warnings

import pytest

from backstep.interceptor import Action
from backstep.registry import InverseRegistry, registry
from backstep.rollback import RollbackEngine
from backstep.store import BackstepStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_actions(store: BackstepStore, session_id: str, specs: list[dict]) -> list[Action]:
    actions = []
    for i, spec in enumerate(specs, start=1):
        a = Action(
            session_id=session_id,
            seq=i,
            tool=spec["tool"],
            args=spec.get("args", {}),
            result=spec.get("result", {"content": "ok"}),
            reversible=spec.get("reversible", True),
            status=spec.get("status", "ok"),
        )
        store.write(a)
        actions.append(a)
    return actions


# ---------------------------------------------------------------------------
# Test 1: multi-file rollback — 5 files written, all 5 deleted
# ---------------------------------------------------------------------------

class TestMultiFileRollback:
    def test_all_five_files_rolled_back(self, tmp_path):
        files = [tmp_path / f"file_{i}.txt" for i in range(5)]
        for f in files:
            f.write_text(f"content of {f.name}")

        store = BackstepStore(str(tmp_path / "multi.db"))
        actions = _write_actions(store, "multi-01", [
            {"tool": "write_file", "args": {"path": str(f)}, "result": {"content": "ok"}}
            for f in files
        ])

        engine = RollbackEngine(store, registry)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = engine.rollback("multi-01")

        assert len(result.rolled_back) == 5
        assert result.skipped == []
        assert result.errors == []
        for f in files:
            assert not f.exists(), f"{f.name} should have been deleted"
        store.close()


# ---------------------------------------------------------------------------
# Test 2: partial rollback — rollback_to(seq=2) only undoes seq > 2
# ---------------------------------------------------------------------------

class TestPartialRollback:
    def test_only_actions_after_seq_undone(self, tmp_path):
        files = [tmp_path / f"partial_{i}.txt" for i in range(1, 4)]
        for f in files:
            f.write_text("data")

        store = BackstepStore(str(tmp_path / "partial.db"))
        _write_actions(store, "partial-01", [
            {"tool": "write_file", "args": {"path": str(f)}, "result": {"content": "ok"}}
            for f in files
        ])

        engine = RollbackEngine(store, registry)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = engine.rollback_to("partial-01", seq=2)

        # Only seq=3 (files[2]) should be deleted
        assert files[0].exists(), "seq=1 file must be untouched"
        assert files[1].exists(), "seq=2 file must be untouched"
        assert not files[2].exists(), "seq=3 file must be deleted"
        assert len(result.rolled_back) == 1
        store.close()


# ---------------------------------------------------------------------------
# Test 3: mixed reversible + committed
# ---------------------------------------------------------------------------

class TestMixedReversibleCommitted:
    def test_only_reversible_actions_rolled_back(self, tmp_path):
        registry.register_committed("send_email")

        file_a = tmp_path / "report_a.txt"
        file_b = tmp_path / "report_b.txt"
        file_a.write_text("a")
        file_b.write_text("b")

        store = BackstepStore(str(tmp_path / "mixed.db"))
        actions = _write_actions(store, "mixed-01", [
            {"tool": "write_file", "args": {"path": str(file_a)}, "result": {"content": "ok"}},
            {"tool": "send_email",  "args": {"to": "x@y.com", "body": "hi"},
             "result": {"content": "sent"}, "status": "committed", "reversible": False},
            {"tool": "write_file", "args": {"path": str(file_b)}, "result": {"content": "ok"}},
        ])

        engine = RollbackEngine(store, registry)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = engine.rollback("mixed-01")

        assert len(result.rolled_back) == 2
        assert len(result.skipped) == 1
        assert result.errors == []
        assert not file_a.exists()
        assert not file_b.exists()

        skipped_action = next(a for a in actions if a.tool == "send_email")
        assert skipped_action.id in result.skipped
        store.close()


# ---------------------------------------------------------------------------
# Test 4: missing inverse — graceful skip, no crash
# ---------------------------------------------------------------------------

class TestMissingInverse:
    def test_no_inverse_goes_to_skipped_not_errors(self, tmp_path):
        reg = InverseRegistry()  # empty — no inverses registered

        store = BackstepStore(str(tmp_path / "skip.db"))
        actions = _write_actions(store, "skip-01", [
            {"tool": "mystery_tool", "args": {"x": 1}},
        ])

        engine = RollbackEngine(store, reg)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = engine.rollback("skip-01")

        assert actions[0].id in result.skipped
        assert result.rolled_back == []
        assert result.errors == []
        assert any("mystery_tool" in str(warning.message) for warning in w)
        store.close()


# ---------------------------------------------------------------------------
# Test 5: inverse raises exception — isolation
# ---------------------------------------------------------------------------

class TestInverseExceptionIsolation:
    def test_failing_inverse_does_not_abort_others(self, tmp_path):
        reg = InverseRegistry()

        boom_calls: list = []
        ok_calls: list = []

        def boom(args: dict, result: dict) -> None:
            boom_calls.append(args)
            raise RuntimeError("simulated disk failure")

        def ok_inverse(args: dict, result: dict) -> None:
            ok_calls.append(args)

        reg.register("boom_tool", boom)
        reg.register("safe_tool", ok_inverse)

        store = BackstepStore(str(tmp_path / "isolation.db"))
        actions = _write_actions(store, "iso-01", [
            {"tool": "safe_tool",  "args": {"n": 1}},
            {"tool": "boom_tool",  "args": {"n": 2}},
            {"tool": "safe_tool",  "args": {"n": 3}},
        ])

        engine = RollbackEngine(store, reg)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = engine.rollback("iso-01")

        # boom_tool lands in errors, both safe_tool calls still executed
        assert actions[1].id in result.errors
        assert len(result.rolled_back) == 2
        assert len(ok_calls) == 2
        # Exception must NOT propagate out of rollback()
        store.close()

    def test_exception_does_not_propagate(self, tmp_path):
        reg = InverseRegistry()
        reg.register("always_fails", lambda args, result: (_ for _ in ()).throw(RuntimeError("boom")))

        store = BackstepStore(str(tmp_path / "nopropagate.db"))
        _write_actions(store, "np-01", [{"tool": "always_fails", "args": {}}])

        engine = RollbackEngine(store, reg)
        # Must not raise
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = engine.rollback("np-01")

        assert len(result.errors) == 1
        store.close()


# ---------------------------------------------------------------------------
# Test 6: plugin loading — inline custom inverse registered and callable
# ---------------------------------------------------------------------------

class TestPluginLoading:
    def test_custom_inverse_registered_and_callable(self, tmp_path):
        """Simulates a plugin registering a custom inverse at import time."""
        custom_reg = InverseRegistry()
        calls: list[dict] = []

        # Simulate what a backstep_mytool plugin's __init__.py would do:
        def undo_custom_tool(args: dict, result: dict) -> None:
            calls.append({"args": args, "result": result})

        custom_reg.register("custom_tool", undo_custom_tool, source="backstep_mytool")

        # Verify it's registered and callable
        assert custom_reg.get_inverse("custom_tool") is not None
        sources = custom_reg.list_registered()
        assert sources["custom_tool"] == "backstep_mytool"

        # Verify it actually runs during rollback
        store = BackstepStore(str(tmp_path / "plugin.db"))
        _write_actions(store, "plugin-01", [
            {"tool": "custom_tool", "args": {"target": "something"}, "result": {"content": "done"}},
        ])

        engine = RollbackEngine(store, custom_reg)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = engine.rollback("plugin-01")

        assert len(result.rolled_back) == 1
        assert len(calls) == 1
        assert calls[0]["args"] == {"target": "something"}
        store.close()

    def test_built_in_inverses_loaded_on_import(self):
        """Importing backstep loads files.py and registers all built-in inverses."""
        sources = registry.list_registered()
        built_ins = {"write_file", "delete_file", "create_dir", "move_file", "append_file"}
        for tool in built_ins:
            assert tool in sources, f"{tool} not registered"
            assert sources[tool] == "backstep_files (built-in)"

    def test_plugins_cli_lists_built_ins(self):
        """backstep plugins command lists backstep_files (built-in)."""
        from click.testing import CliRunner
        from backstep.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["plugins"])
        assert result.exit_code == 0
        assert "backstep_files (built-in)" in result.output
        assert "write_file" in result.output
