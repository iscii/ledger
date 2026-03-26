"""
ledger.store
~~~~~~~~~~~~
SQLite-backed persistence for Action objects.

Schema
------
A single ``actions`` table stores each Action as a JSON blob alongside
the four indexed/queryable columns used for session queries:

    id          TEXT PRIMARY KEY
    session_id  TEXT NOT NULL
    seq         INTEGER NOT NULL
    ts          TEXT NOT NULL        -- ISO-8601 UTC
    data        TEXT NOT NULL        -- full Action as JSON

Usage::

    store = LedgerStore("./ledger.db")
    store.write(action)
    actions = store.get_session("session-01")
    sessions = store.list_sessions()
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ledger.interceptor import Action


_DDL = """
CREATE TABLE IF NOT EXISTS actions (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    ts         TEXT NOT NULL,
    data       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_actions_session_id ON actions (session_id);
"""


class LedgerStore:
    """Persist and query :class:`~ledger.interceptor.Action` objects."""

    def __init__(self, path: str | Path = "./ledger.db") -> None:
        self._path = Path(path)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.executescript(_DDL)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write(self, action: Action) -> None:
        """Persist *action*, replacing any existing row with the same id."""
        self._conn.execute(
            "INSERT OR REPLACE INTO actions (id, session_id, seq, ts, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                action.id,
                action.session_id,
                action.seq,
                action.ts.isoformat(),
                action.model_dump_json(),
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_action(self, action_id: str) -> Action | None:
        """Return the Action with *action_id*, or ``None`` if not found."""
        row = self._conn.execute(
            "SELECT data FROM actions WHERE id = ?", (action_id,)
        ).fetchone()
        return Action.model_validate_json(row[0]) if row else None

    def get_session(self, session_id: str) -> list[Action]:
        """Return all Actions for *session_id*, ordered by seq."""
        rows = self._conn.execute(
            "SELECT data FROM actions WHERE session_id = ? ORDER BY seq",
            (session_id,),
        ).fetchall()
        return [Action.model_validate_json(row[0]) for row in rows]

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return summary metadata for every session in the store.

        Each entry is a dict with keys:
            session_id, action_count, started_at, last_action_at
        """
        rows = self._conn.execute(
            """
            SELECT
                session_id,
                COUNT(*)    AS action_count,
                MIN(ts)     AS started_at,
                MAX(ts)     AS last_action_at
            FROM actions
            GROUP BY session_id
            ORDER BY started_at
            """
        ).fetchall()
        return [
            {
                "session_id": r[0],
                "action_count": r[1],
                "started_at": r[2],
                "last_action_at": r[3],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()
