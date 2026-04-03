"""
backstep.mcp_tools
~~~~~~~~~~~~~~~~~~
Tool definitions for exposing Backstep operations as MCP (Model Context
Protocol) tools that Claude can call during an agent session.

These wrap the ReplayEngine and RollbackEngine with descriptions and
parameter schemas so an MCP host can expose them to a language model.

Usage (with an MCP host that supports callable tool registration)::

    from backstep.mcp_tools import get_mcp_tools
    tools = get_mcp_tools(db_path="./backstep.db")
    # Register `tools` with your MCP host

Each tool is a dict compatible with the Anthropic tool-use schema:
    {
        "name": str,
        "description": str,
        "input_schema": { "type": "object", "properties": {...} },
    }
Together with a matching callable keyed by tool name.
"""

from __future__ import annotations

from typing import Any

from backstep.config import get_db_path
from backstep.registry import registry
from backstep.replay import ReplayEngine
from backstep.rollback import RollbackEngine
from backstep.store import BackstepStore
from backstep.tool_registry import tool_registry


# ---------------------------------------------------------------------------
# Tool schemas (Anthropic-compatible)
# ---------------------------------------------------------------------------

_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "rollback_session",
        "description": (
            "Roll back recorded actions in a Backstep session using registered "
            "inverse functions.  If seqs is omitted, all reversible actions are "
            "rolled back in reverse order.  Example: seqs=[3,5] rolls back only "
            "actions #3 and #5."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session ID to roll back.",
                },
                "seqs": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": (
                        "Optional list of seq numbers to roll back.  "
                        "If omitted, all actions are targeted."
                    ),
                },
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "replay_session",
        "description": (
            "Re-execute tool calls from a Backstep session without invoking the "
            "LLM.  Useful for restoring state after a disaster.  If seqs, "
            "from_seq, and to_seq are all omitted, every action is replayed.  "
            "seqs and from_seq/to_seq are mutually exclusive."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session ID to replay.",
                },
                "seqs": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Specific seq numbers to replay.",
                },
                "from_seq": {
                    "type": "integer",
                    "description": "Replay from this seq number (inclusive).",
                },
                "to_seq": {
                    "type": "integer",
                    "description": "Replay up to this seq number (inclusive).",
                },
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "get_feasibility",
        "description": (
            "Check whether actions in a session can be rolled back.  Returns "
            "per-action status (has inverse / committed / no inverse).  Pass "
            "seqs to check a subset."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session ID to inspect.",
                },
                "seqs": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional seq numbers to restrict the check.",
                },
            },
            "required": ["session_id"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool callables
# ---------------------------------------------------------------------------

def _make_rollback_fn(db_path: str):
    def rollback_session(session_id: str, seqs: list[int] | None = None) -> dict[str, Any]:
        store = BackstepStore(db_path)
        engine = RollbackEngine(store, registry)
        result = engine.rollback(session_id, seqs=seqs)
        store.close()
        return {
            "session_id": result.session_id,
            "rolled_back": result.rolled_back,
            "skipped": result.skipped,
            "errors": result.errors,
        }
    return rollback_session


def _make_replay_fn(db_path: str):
    def replay_session(
        session_id: str,
        seqs: list[int] | None = None,
        from_seq: int | None = None,
        to_seq: int | None = None,
    ) -> dict[str, Any]:
        store = BackstepStore(db_path)
        selected: list[int] | None = seqs
        if selected is None and (from_seq is not None or to_seq is not None):
            actions = store.get_session(session_id)
            all_seqs = [a.seq for a in actions]
            lo = from_seq if from_seq is not None else (min(all_seqs) if all_seqs else 1)
            hi = to_seq   if to_seq   is not None else (max(all_seqs) if all_seqs else 1)
            selected = [s for s in all_seqs if lo <= s <= hi]
        engine = ReplayEngine(store, tool_registry)
        result = engine.replay(session_id, seqs=selected)
        store.close()
        return {
            "session_id": result.session_id,
            "replayed": result.replayed,
            "skipped": result.skipped,
            "errors": result.errors,
        }
    return replay_session


def _make_feasibility_fn(db_path: str):
    def get_feasibility(session_id: str, seqs: list[int] | None = None) -> dict[str, Any]:
        store = BackstepStore(db_path)
        engine = RollbackEngine(store, registry)
        result = engine.can_rollback(session_id, seqs=seqs)
        store.close()
        return {
            "session_id": result.session_id,
            "feasible": result.feasible,
            "actions": [
                {"seq": af.seq, "tool": af.tool,
                 "can_rollback": af.can_rollback, "reason": af.reason}
                for af in result.actions
            ],
            "actions_that_can_rollback": result.actions_that_can_rollback,
            "actions_that_cannot": result.actions_that_cannot,
        }
    return get_feasibility


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_mcp_tools(db_path: str | None = None) -> dict[str, Any]:
    """Return MCP tool schemas and callables for the given database.

    Args:
        db_path: Path to the SQLite database.  Defaults to ``get_db_path()``.

    Returns:
        Dict with:
          ``schemas``   — list of Anthropic-compatible tool schema dicts
          ``callables`` — dict mapping tool name → callable
    """
    path = db_path or str(get_db_path())
    return {
        "schemas": _TOOL_SCHEMAS,
        "callables": {
            "rollback_session": _make_rollback_fn(path),
            "replay_session":   _make_replay_fn(path),
            "get_feasibility":  _make_feasibility_fn(path),
        },
    }
