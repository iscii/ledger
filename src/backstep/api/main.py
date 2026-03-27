"""
backstep.api.main
~~~~~~~~~~~~~~~~~
FastAPI application serving session, diff, rollback, and replay endpoints.
This is the backend consumed by the Vue 3 UI (Stage 6).

Configuration (env vars)
------------------------
  BACKSTEP_DB          Path to SQLite database.  Default: ./backstep.db
  BACKSTEP_API_PORT    Port to listen on.         Default: 7842

Run
---
  uv run backstep-api
  # or
  uvicorn backstep.api.main:app --port 7842

Endpoints
---------
  GET  /health
  GET  /sessions
  GET  /sessions/{session_id}
  GET  /diff/{session_a}/{session_b}
  POST /sessions/{session_id}/rollback
  POST /sessions/{session_id}/replay
"""

from __future__ import annotations

import os
import warnings
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backstep.diff import DiffEngine, DiffResult, ActionDiff
from backstep.interceptor import Action
from backstep.registry import registry
from backstep.rollback import RollbackEngine
from backstep.store import BackstepStore
from backstep.tool_registry import tool_registry


# ---------------------------------------------------------------------------
# App + CORS
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Backstep API",
    description="Session viewer, diff, rollback, and replay endpoints.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# DB helper — always reads from disk, never caches in memory
# ---------------------------------------------------------------------------

def _db() -> BackstepStore:
    path = os.getenv("BACKSTEP_DB", "./backstep.db")
    return BackstepStore(path)


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _action_dict(a: Action) -> dict[str, Any]:
    return a.model_dump(mode="json")


def _session_exists(store: BackstepStore, session_id: str) -> bool:
    return any(s["session_id"] == session_id for s in store.list_sessions())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sessions")
def list_sessions() -> list[dict[str, Any]]:
    """List all recorded sessions with metadata."""
    store = _db()
    rows = store.list_sessions()
    store.close()
    return rows


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    """Return full session with all Actions."""
    store = _db()
    if not _session_exists(store, session_id):
        store.close()
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    actions = store.get_session(session_id)
    store.close()
    return {
        "session_id": session_id,
        "actions": [_action_dict(a) for a in actions],
    }


@app.get("/diff/{session_a}/{session_b}")
def get_diff(session_a: str, session_b: str) -> dict[str, Any]:
    """Return a structured diff between two sessions."""
    store = _db()
    missing = [s for s in (session_a, session_b) if not _session_exists(store, s)]
    if missing:
        store.close()
        raise HTTPException(
            status_code=404,
            detail=f"Session(s) not found: {', '.join(missing)}",
        )
    engine = DiffEngine(store)
    result = engine.diff(session_a, session_b)
    store.close()
    return _diff_result_dict(result)


@app.post("/sessions/{session_id}/rollback")
def rollback_session(session_id: str) -> dict[str, Any]:
    """Roll back all actions in a session using registered inverses."""
    store = _db()
    if not _session_exists(store, session_id):
        store.close()
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    engine = RollbackEngine(store, registry)
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        result = engine.rollback(session_id)
    store.close()
    return {
        "session_id": result.session_id,
        "rolled_back": result.rolled_back,
        "skipped": result.skipped,
        "errors": result.errors,
    }


@app.post("/sessions/{session_id}/replay")
def replay_session(session_id: str) -> dict[str, Any]:
    """Re-execute all tool calls in a session without invoking the LLM."""
    store = _db()
    if not _session_exists(store, session_id):
        store.close()
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    actions = store.get_session(session_id)
    store.close()

    replayed = 0
    errors: list[str] = []
    for action in actions:
        fn = tool_registry.get(action.tool)
        if fn is None:
            continue
        try:
            fn(**action.args)
            replayed += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{action.id}: {exc}")

    return {
        "session_id": session_id,
        "replayed": replayed,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _action_diff_dict(d: ActionDiff) -> dict[str, Any]:
    return {
        "kind": d.kind,
        "seq": d.seq,
        "tool": d.tool,
        "action_a": _action_dict(d.action_a) if d.action_a else None,
        "action_b": _action_dict(d.action_b) if d.action_b else None,
        "changes": d.changes,
    }


def _diff_result_dict(r: DiffResult) -> dict[str, Any]:
    return {
        "session_a": r.session_a,
        "session_b": r.session_b,
        "is_identical": r.is_identical,
        "actions": [_action_diff_dict(d) for d in r.actions],
    }


# ---------------------------------------------------------------------------
# Entry point for `uv run backstep-api`
# ---------------------------------------------------------------------------

def start() -> None:
    import uvicorn
    port = int(os.getenv("BACKSTEP_API_PORT", "7842"))
    uvicorn.run("backstep.api.main:app", host="0.0.0.0", port=port, reload=False)
