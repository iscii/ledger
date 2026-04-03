"""
backstep.api.main
~~~~~~~~~~~~~~~~~
FastAPI application serving session, diff, rollback, and replay endpoints.
This is the backend consumed by the Vue 3 UI (Stage 6).

Configuration (env vars)
------------------------
  BACKSTEP_DB          Path to SQLite database.  Default: ./backstep.db (cwd-relative)
  BACKSTEP_API_PORT    Port to listen on.         Default: 7842

Run
---
  uv run backstep-api
  # or
  uvicorn backstep.api.main:app --port 7842

Endpoints
---------
  GET  /health
  GET  /config
  GET  /sessions
  GET  /sessions/{session_id}
  GET  /sessions/{session_id}/feasibility
  GET  /diff/{session_a}/{session_b}
  POST /sessions/{session_id}/rollback
  POST /sessions/{session_id}/replay
"""

from __future__ import annotations

import os
import warnings
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backstep.config import get_db_path
from backstep.diff import DiffEngine, DiffResult, ActionDiff
from backstep.interceptor import Action
from backstep.registry import registry
from backstep.replay import ReplayEngine
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
# Request body models
# ---------------------------------------------------------------------------

class RollbackRequest(BaseModel):
    seqs: list[int] | None = None
    """Specific seq numbers to roll back.  None = all."""


class ReplayRequest(BaseModel):
    seqs: list[int] | None = None
    """Specific seq numbers to replay.  None = all."""
    from_seq: int | None = None
    """Replay from this seq number (inclusive).  Ignored if seqs is set."""
    to_seq: int | None = None
    """Replay up to this seq number (inclusive).  Ignored if seqs is set."""


# ---------------------------------------------------------------------------
# DB helper — always reads from disk, never caches in memory
# ---------------------------------------------------------------------------

def _db() -> BackstepStore:
    return BackstepStore(get_db_path())


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


@app.get("/config")
def get_config() -> dict[str, Any]:
    """Return active runtime configuration."""
    return {
        "db_path": str(get_db_path()),
        "api_port": int(os.getenv("BACKSTEP_API_PORT", "7842")),
    }


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


@app.get("/sessions/{session_id}/feasibility")
def session_feasibility(
    session_id: str,
    seqs: str | None = Query(default=None, description="Comma-separated seq numbers, e.g. 3,5,6"),
) -> dict[str, Any]:
    """Return rollback feasibility for a session.

    Optional query param ``seqs`` restricts the check to specific actions.
    """
    store = _db()
    if not _session_exists(store, session_id):
        store.close()
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    parsed_seqs: list[int] | None = None
    if seqs:
        try:
            parsed_seqs = [int(s.strip()) for s in seqs.split(",") if s.strip()]
        except ValueError:
            store.close()
            raise HTTPException(status_code=422, detail="seqs must be comma-separated integers.")
    engine = RollbackEngine(store, registry)
    result = engine.can_rollback(session_id, seqs=parsed_seqs)
    store.close()
    return {
        "session_id": result.session_id,
        "feasible": result.feasible,
        "actions": [
            {
                "seq": af.seq,
                "tool": af.tool,
                "can_rollback": af.can_rollback,
                "reason": af.reason,
            }
            for af in result.actions
        ],
        "actions_that_can_rollback": result.actions_that_can_rollback,
        "actions_that_cannot": result.actions_that_cannot,
        "blocking_committed": result.blocking_committed,
    }


@app.post("/sessions/{session_id}/rollback")
def rollback_session(session_id: str, body: RollbackRequest = RollbackRequest()) -> dict[str, Any]:
    """Roll back actions in a session using registered inverses.

    Optionally pass ``{"seqs": [3, 5, 6]}`` in the request body to target
    specific actions.  Omit the body (or set ``seqs`` to null) to roll back
    all actions.
    """
    store = _db()
    if not _session_exists(store, session_id):
        store.close()
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    engine = RollbackEngine(store, registry)
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        result = engine.rollback(session_id, seqs=body.seqs)
    store.close()
    return {
        "session_id": result.session_id,
        "rolled_back": result.rolled_back,
        "skipped": result.skipped,
        "errors": result.errors,
    }


@app.post("/sessions/{session_id}/replay")
def replay_session(session_id: str, body: ReplayRequest = ReplayRequest()) -> dict[str, Any]:
    """Re-execute tool calls in a session without invoking the LLM.

    Optional body fields:
      ``seqs``     — list of specific seq numbers to replay
      ``from_seq`` — replay from this seq (inclusive)
      ``to_seq``   — replay up to this seq (inclusive)

    If all are omitted, every action is replayed.
    ``seqs`` and ``from_seq``/``to_seq`` are mutually exclusive.
    """
    store = _db()
    if not _session_exists(store, session_id):
        store.close()
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    # Resolve seq selection
    if body.seqs is not None and (body.from_seq is not None or body.to_seq is not None):
        store.close()
        raise HTTPException(status_code=422, detail="Use either seqs or from_seq/to_seq, not both.")

    selected: list[int] | None = None
    if body.seqs is not None:
        selected = body.seqs
    elif body.from_seq is not None or body.to_seq is not None:
        actions = store.get_session(session_id)
        all_seqs = [a.seq for a in actions]
        lo = body.from_seq if body.from_seq is not None else (min(all_seqs) if all_seqs else 1)
        hi = body.to_seq   if body.to_seq   is not None else (max(all_seqs) if all_seqs else 1)
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
    print(f"[backstep] DB: {get_db_path()}", flush=True)
    port = int(os.getenv("BACKSTEP_API_PORT", "7842"))
    uvicorn.run("backstep.api.main:app", host="0.0.0.0", port=port, reload=False)


def start_with_ui() -> None:
    """Build the frontend then serve it as static files alongside the API."""
    import subprocess
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles

    frontend = Path(__file__).parent.parent.parent.parent / "frontend"
    dist = frontend / "dist"

    if frontend.exists():
        subprocess.run(["npm", "run", "build"], cwd=str(frontend), check=True)
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="static")

    start()
