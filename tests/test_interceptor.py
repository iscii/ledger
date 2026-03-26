"""
tests/test_interceptor.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for ledger.interceptor.

Structure
---------
1.  ``simple_agent`` — a plain Anthropic agent with three tools
    (read_file, write_file, list_dir).  Written with *no knowledge* of
    Ledger; the exact code an agent author would write.

2.  Unit tests that mock ``Messages.create`` at the class level and
    verify the interceptor captures every tool call + result correctly.

3.  A ``__main__`` block you can run manually against a real API key to
    see the pretty-printed Action JSON in your terminal.

Kill-risk check
---------------
The ``simple_agent`` function is called both inside and outside a
``ledger.session()`` block.  If it requires ANY modification to work
with Ledger, the design is broken.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

import anthropic
import ledger
from ledger.interceptor import Action, LedgerSession, _patched, _patched_create
from ledger.store import LedgerStore


# ---------------------------------------------------------------------------
# Test agent — written with zero knowledge of Ledger
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "read_file",
        "description": "Return the contents of a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_dir",
        "description": "List files in a directory.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
]

# Simulated filesystem used by the agent
_FS: dict[str, str] = {
    "config.txt": "debug=true\nport=8080\n",
}


def simple_agent(client: anthropic.Anthropic, prompt: str) -> str:
    """A normal Anthropic agent.  No Ledger imports, no Ledger knowledge."""
    messages = [{"role": "user", "content": prompt}]

    while True:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if block.type == "text":
                    return block.text
            return ""

        # Execute tools locally and build tool_result list
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            name, args = block.name, block.input
            if name == "read_file":
                result = _FS.get(args["path"], f"error: {args['path']} not found")
            elif name == "write_file":
                _FS[args["path"]] = args["content"]
                result = "ok"
            elif name == "list_dir":
                result = "\n".join(_FS.keys())
            else:
                result = f"unknown tool: {name}"

            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": result}
            )

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _tool_use_block(tool_id: str, name: str, input_: dict) -> MagicMock:
    b = MagicMock()
    b.type = "tool_use"
    b.id = tool_id
    b.name = name
    b.input = input_
    return b


def _text_block(text: str) -> MagicMock:
    b = MagicMock()
    b.type = "text"
    b.text = text
    return b


def _response(content: list, stop_reason: str = "end_turn") -> MagicMock:
    r = MagicMock()
    r.content = content
    r.stop_reason = stop_reason
    return r


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestActionSchema:
    """Action objects must match the canonical schema exactly."""

    def test_fields_exist(self):
        a = Action(session_id="s1", seq=1, tool="read_file", args={"path": "x.txt"})
        assert a.id  # uuid4 string
        assert a.session_id == "s1"
        assert a.seq == 1
        assert isinstance(a.ts, datetime)
        assert a.ts.tzinfo is not None  # UTC-aware
        assert a.tool == "read_file"
        assert a.args == {"path": "x.txt"}
        assert a.result == {}
        assert a.reversible is True
        assert a.inverse_id is None
        assert a.status == "ok"

    def test_status_values(self):
        for s in ("ok", "error", "committed"):
            a = Action(session_id="s", seq=1, tool="t", args={}, status=s)
            assert a.status == s

    def test_invalid_status_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            Action(session_id="s", seq=1, tool="t", args={}, status="bad")

    def test_json_roundtrip(self):
        a = Action(session_id="s", seq=1, tool="read_file", args={"path": "f"})
        dumped = json.loads(a.model_dump_json())
        assert dumped["tool"] == "read_file"
        assert dumped["seq"] == 1


class TestInterceptorCapture:
    """Core interception logic."""

    def _run_agent_with_mock_responses(self, responses: list) -> tuple[LedgerSession, list]:
        """Run simple_agent against a sequence of mock responses inside a session."""
        call_idx = [0]

        def mock_create(self_inner, *args, **kwargs):
            r = responses[call_idx[0]]
            call_idx[0] += 1
            return r

        with patch("anthropic.resources.messages.Messages.create", mock_create):
            client = anthropic.Anthropic(api_key="test-key")
            with ledger.session("test-session") as sess:
                simple_agent(client, "Read config.txt then write a summary.")
        return sess, sess.actions

    def test_two_tool_calls_captured(self):
        responses = [
            _response(
                [_tool_use_block("tu_001", "read_file", {"path": "config.txt"})],
                stop_reason="tool_use",
            ),
            _response(
                [_tool_use_block("tu_002", "write_file", {"path": "summary.txt", "content": "debug=true"})],
                stop_reason="tool_use",
            ),
            _response([_text_block("Done.")]),
        ]
        sess, actions = self._run_agent_with_mock_responses(responses)
        assert len(actions) == 2

    def test_seq_is_one_based_and_increments(self):
        responses = [
            _response(
                [_tool_use_block("tu_001", "read_file", {"path": "a"})],
                stop_reason="tool_use",
            ),
            _response(
                [_tool_use_block("tu_002", "list_dir", {"path": "."})],
                stop_reason="tool_use",
            ),
            _response([_text_block("ok")]),
        ]
        sess, actions = self._run_agent_with_mock_responses(responses)
        assert actions[0].seq == 1
        assert actions[1].seq == 2

    def test_action_fields_match_schema(self):
        responses = [
            _response(
                [_tool_use_block("tu_001", "read_file", {"path": "config.txt"})],
                stop_reason="tool_use",
            ),
            _response([_text_block("done")]),
        ]
        sess, actions = self._run_agent_with_mock_responses(responses)
        a = actions[0]
        assert a.session_id == "test-session"
        assert a.seq == 1
        assert a.tool == "read_file"
        assert a.args == {"path": "config.txt"}
        # result comes from agent's local execution: "debug=true\nport=8080\n"
        assert a.result == {"content": "debug=true\nport=8080\n"}
        assert a.reversible is True
        assert a.inverse_id is None
        assert a.status == "ok"
        assert isinstance(a.ts, datetime)

    def test_result_matched_to_correct_action_by_tool_use_id(self):
        """Multiple tools in one turn — results must not be cross-wired."""
        responses = [
            _response(
                [
                    _tool_use_block("tu_A", "read_file", {"path": "a.txt"}),
                    _tool_use_block("tu_B", "list_dir", {"path": "/"}),
                ],
                stop_reason="tool_use",
            ),
            _response([_text_block("all done")]),
        ]
        # Agent will try to execute both tools and return results for both.
        # We override _FS so the results are predictable.
        _FS["a.txt"] = "alpha"

        call_idx = [0]

        def mock_create(self_inner, *args, **kwargs):
            r = responses[call_idx[0]]
            call_idx[0] += 1
            return r

        with patch("anthropic.resources.messages.Messages.create", mock_create):
            client = anthropic.Anthropic(api_key="test-key")
            with ledger.session("multi-tool") as sess:
                simple_agent(client, "Do two things.")

        assert len(sess.actions) == 2
        by_tool = {a.tool: a for a in sess.actions}
        assert by_tool["read_file"].result == {"content": "alpha"}
        assert by_tool["list_dir"].result["content"]  # non-empty listing

    def test_actions_printed_to_stdout(self, capsys):
        responses = [
            _response(
                [_tool_use_block("tu_p", "read_file", {"path": "config.txt"})],
                stop_reason="tool_use",
            ),
            _response([_text_block("ok")]),
        ]
        sess, actions = self._run_agent_with_mock_responses(responses)
        captured = capsys.readouterr().out
        assert captured.strip()
        # Must be valid JSON
        data = json.loads(captured.strip())
        assert data["tool"] == "read_file"


class TestPatchLifecycle:
    """The monkey-patch is installed and removed at the right times."""

    def test_patch_installed_inside_session_removed_after(self):
        from ledger.interceptor import _patched as _p_ref
        import ledger.interceptor as _mod

        assert not _mod._patched  # nothing active

        def noop_create(self_inner, *args, **kwargs):
            r = MagicMock()
            r.content = [_text_block("hi")]
            r.stop_reason = "end_turn"
            return r

        with patch("anthropic.resources.messages.Messages.create", noop_create):
            client = anthropic.Anthropic(api_key="x")
            with ledger.session("lc-test"):
                assert _mod._patched  # installed while inside

        assert not _mod._patched  # removed after exit

    def test_agent_works_identically_without_ledger(self):
        """Zero-change requirement: same agent, same results, no Ledger."""
        responses = [
            _response(
                [_tool_use_block("tu_z", "read_file", {"path": "config.txt"})],
                stop_reason="tool_use",
            ),
            _response([_text_block("standalone result")]),
        ]
        call_idx = [0]

        def mock_create(self_inner, *args, **kwargs):
            r = responses[call_idx[0]]
            call_idx[0] += 1
            return r

        with patch("anthropic.resources.messages.Messages.create", mock_create):
            client = anthropic.Anthropic(api_key="test-key")
            # Run WITHOUT Ledger — must work fine
            result = simple_agent(client, "read config")

        assert result == "standalone result"

    def test_nested_sessions_share_patch(self):
        import ledger.interceptor as _mod

        call_count = [0]

        def noop_create(self_inner, *args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            r.content = [_text_block("hi")]
            r.stop_reason = "end_turn"
            return r

        with patch("anthropic.resources.messages.Messages.create", noop_create):
            client = anthropic.Anthropic(api_key="x")
            with ledger.session("outer") as outer:
                assert _mod._patched
                with ledger.session("inner") as inner:
                    assert _mod._patched
                    simple_agent(client, "hi")
                # patch still active (outer still open)
                assert _mod._patched

        assert not _mod._patched


# ---------------------------------------------------------------------------
# Persistence tests (Stage 2)
# ---------------------------------------------------------------------------

_TEST_DB = "./test_ledger.db"


class TestPersistence:
    """Actions written to SQLite survive the session context manager."""

    def _three_tool_responses(self) -> list:
        return [
            _response(
                [_tool_use_block("tp_001", "list_dir", {"path": "."})],
                stop_reason="tool_use",
            ),
            _response(
                [_tool_use_block("tp_002", "read_file", {"path": "config.txt"})],
                stop_reason="tool_use",
            ),
            _response(
                [_tool_use_block("tp_003", "write_file", {"path": "out.txt", "content": "summary"})],
                stop_reason="tool_use",
            ),
            _response([_text_block("All done.")]),
        ]

    def setup_method(self):
        # Remove any leftover DB from a previous run
        if os.path.exists(_TEST_DB):
            os.remove(_TEST_DB)

    def teardown_method(self):
        if os.path.exists(_TEST_DB):
            os.remove(_TEST_DB)

    def test_actions_persisted_to_db(self):
        responses = self._three_tool_responses()
        call_idx = [0]

        def mock_create(self_inner, *args, **kwargs):
            r = responses[call_idx[0]]
            call_idx[0] += 1
            return r

        with patch("anthropic.resources.messages.Messages.create", mock_create):
            client = anthropic.Anthropic(api_key="test-key")
            with ledger.session("persist-01", db=_TEST_DB) as sess:
                simple_agent(client, "List, read, write.")

        # Session is over — open the DB independently
        store = LedgerStore(_TEST_DB)

        sessions = store.list_sessions()
        assert any(s["session_id"] == "persist-01" for s in sessions)

        actions = store.get_session("persist-01")
        assert len(actions) == 3

        # Canonical schema check on every action
        for a in actions:
            assert isinstance(a, Action)
            assert a.session_id == "persist-01"
            assert a.seq in (1, 2, 3)
            assert isinstance(a.ts, datetime)
            assert a.ts.tzinfo is not None
            assert a.tool in ("list_dir", "read_file", "write_file")
            assert isinstance(a.args, dict)
            assert isinstance(a.result, dict)
            assert a.status == "ok"
            assert a.reversible is True
            assert a.inverse_id is None

        store.close()

    def test_list_sessions_metadata(self):
        responses = self._three_tool_responses()
        call_idx = [0]

        def mock_create(self_inner, *args, **kwargs):
            r = responses[call_idx[0]]
            call_idx[0] += 1
            return r

        with patch("anthropic.resources.messages.Messages.create", mock_create):
            client = anthropic.Anthropic(api_key="test-key")
            with ledger.session("meta-01", db=_TEST_DB):
                simple_agent(client, "List, read, write.")

        store = LedgerStore(_TEST_DB)
        sessions = store.list_sessions()
        assert len(sessions) == 1
        s = sessions[0]
        assert s["session_id"] == "meta-01"
        assert s["action_count"] == 3
        assert s["started_at"] is not None
        assert s["last_action_at"] is not None
        store.close()

    def test_get_action_by_id(self):
        responses = self._three_tool_responses()
        call_idx = [0]

        def mock_create(self_inner, *args, **kwargs):
            r = responses[call_idx[0]]
            call_idx[0] += 1
            return r

        with patch("anthropic.resources.messages.Messages.create", mock_create):
            client = anthropic.Anthropic(api_key="test-key")
            with ledger.session("id-test", db=_TEST_DB) as sess:
                simple_agent(client, "List, read, write.")

        store = LedgerStore(_TEST_DB)
        for original in sess.actions:
            fetched = store.get_action(original.id)
            assert fetched is not None
            assert fetched.id == original.id
            assert fetched.tool == original.tool
        store.close()

    def test_db_none_does_not_create_file(self):
        """db=None means stdout only — no DB file created."""
        responses = [
            _response(
                [_tool_use_block("tn_001", "read_file", {"path": "config.txt"})],
                stop_reason="tool_use",
            ),
            _response([_text_block("ok")]),
        ]
        call_idx = [0]

        def mock_create(self_inner, *args, **kwargs):
            r = responses[call_idx[0]]
            call_idx[0] += 1
            return r

        with patch("anthropic.resources.messages.Messages.create", mock_create):
            client = anthropic.Anthropic(api_key="test-key")
            with ledger.session("no-db", db=None):
                simple_agent(client, "read")

        assert not os.path.exists(_TEST_DB)


# ---------------------------------------------------------------------------
# Manual smoke-test (real API key required)
# ---------------------------------------------------------------------------

def _live_demo() -> None:
    """
    Run this block manually to see real Action JSON printed to stdout.

        ANTHROPIC_API_KEY=sk-... python tests/test_interceptor.py

    The agent has NO knowledge of Ledger — the wrapper is applied externally.
    """
    import os
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Set ANTHROPIC_API_KEY to run the live demo.")
        return

    client = anthropic.Anthropic(api_key=api_key)

    print("=" * 60)
    print("STANDALONE (no Ledger):")
    print("=" * 60)
    result = simple_agent(client, "List the files, then read config.txt, then write a one-line summary to out.txt.")
    print(f"Agent returned: {result!r}")

    print()
    print("=" * 60)
    print("WRAPPED WITH ledger.session() — zero agent changes:")
    print("=" * 60)
    _FS.clear()
    _FS["config.txt"] = "debug=true\nport=8080\n"

    with ledger.session("live-demo-01") as sess:
        result = simple_agent(client, "List the files, then read config.txt, then write a one-line summary to out.txt.")

    print(f"\nAgent returned: {result!r}")
    print(f"\nCaptured {len(sess.actions)} action(s):")
    for a in sess.actions:
        print(f"  seq={a.seq}  tool={a.tool}  id={a.id[:8]}...")


if __name__ == "__main__":
    _live_demo()
