"""
tests/test_api.py
~~~~~~~~~~~~~~~~~
Tests for the FastAPI backend (src/backstep/api/main.py).
"""

from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

from backstep.interceptor import Action
from backstep.store import BackstepStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture()
def client(db_path, monkeypatch):
    monkeypatch.setenv("BACKSTEP_DB", db_path)
    # Re-import app after env var is set so _db() picks up the right path
    from backstep.api.main import app
    return TestClient(app)


def _seed(db_path: str, session_id: str, specs: list[dict]) -> list[Action]:
    store = BackstepStore(db_path)
    actions = []
    for i, s in enumerate(specs, start=1):
        a = Action(
            session_id=session_id,
            seq=i,
            tool=s["tool"],
            args=s.get("args", {}),
            result=s.get("result", {"content": "ok"}),
            reversible=s.get("reversible", True),
            status=s.get("status", "ok"),
        )
        store.write(a)
        actions.append(a)
    store.close()
    return actions


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestListSessions:
    def test_list_sessions_empty(self, client):
        r = client.get("/sessions")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_sessions_contains_seeded(self, client, db_path):
        _seed(db_path, "demo-01", [
            {"tool": "list_dir", "args": {"path": "."}},
            {"tool": "read_file", "args": {"path": "f.txt"}},
        ])
        r = client.get("/sessions")
        assert r.status_code == 200
        ids = [s["session_id"] for s in r.json()]
        assert "demo-01" in ids
        demo = next(s for s in r.json() if s["session_id"] == "demo-01")
        assert demo["action_count"] == 2


class TestGetSession:
    def test_get_session(self, client, db_path):
        _seed(db_path, "show-01", [
            {"tool": "read_file", "args": {"path": "a.txt"}, "result": {"content": "hello"}},
        ])
        r = client.get("/sessions/show-01")
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == "show-01"
        assert len(body["actions"]) == 1
        assert body["actions"][0]["tool"] == "read_file"

    def test_get_session_404(self, client):
        r = client.get("/sessions/does-not-exist")
        assert r.status_code == 404


class TestGetDiff:
    def test_get_diff(self, client, db_path):
        specs = [{"tool": "list_dir", "args": {"path": "."}}]
        _seed(db_path, "diff-a", specs)
        _seed(db_path, "diff-b", specs)

        r = client.get("/diff/diff-a/diff-b")
        assert r.status_code == 200
        body = r.json()
        assert body["session_a"] == "diff-a"
        assert body["session_b"] == "diff-b"
        assert body["is_identical"] is True
        assert len(body["actions"]) == 1
        assert body["actions"][0]["kind"] == "same"

    def test_get_diff_404(self, client):
        r = client.get("/diff/missing-a/missing-b")
        assert r.status_code == 404


class TestRollback:
    def test_rollback(self, client, db_path, tmp_path):
        out_file = tmp_path / "rollback_target.txt"
        out_file.write_text("written by agent")

        _seed(db_path, "rb-api-01", [
            {"tool": "write_file", "args": {"path": str(out_file)}, "result": {"content": "ok"}},
        ])

        assert out_file.exists()
        r = client.post("/sessions/rb-api-01/rollback")
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == "rb-api-01"
        assert len(body["rolled_back"]) == 1
        assert body["errors"] == []
        assert not out_file.exists()

    def test_rollback_404(self, client):
        r = client.post("/sessions/missing/rollback")
        assert r.status_code == 404
