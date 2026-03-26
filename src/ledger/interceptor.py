"""
ledger.interceptor
~~~~~~~~~~~~~~~~~~
Monkey-patches anthropic.resources.messages.Messages.create so that every
tool-use / tool-result exchange that passes through ANY Anthropic client
instance is recorded as a canonical Action object — with zero changes
required to the agent being wrapped.

Lifecycle
---------
1. ``ledger.session(id).__enter__`` pushes a LedgerSession onto a
   thread-local stack and installs the patch (idempotent).
2. The patched ``create`` method:
      a. Scans the *incoming* ``messages`` list for ``tool_result`` blocks
         and resolves the matching pending Action.
      b. Calls the *original* ``create``.
      c. Scans the *response* for ``tool_use`` blocks and registers new
         pending Actions.
3. ``ledger.session(id).__exit__`` flushes any Actions that never
   received a result, pops the session, and (when the stack is empty)
   removes the patch.

Each Action is printed to stdout as pretty JSON when it is fully resolved
(call + result).  Pending actions that are flushed on exit are printed
without a result.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any, Literal
import uuid

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Canonical Action schema
# ---------------------------------------------------------------------------

class Action(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    seq: int
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tool: str
    args: dict
    result: dict = Field(default_factory=dict)
    reversible: bool = True
    inverse_id: str | None = None
    status: Literal["ok", "error", "committed"] = "ok"


# ---------------------------------------------------------------------------
# Thread-local session stack
# ---------------------------------------------------------------------------

_local = threading.local()


def _get_sessions() -> list[LedgerSession]:
    if not hasattr(_local, "sessions"):
        _local.sessions = []
    return _local.sessions


def _active_session() -> LedgerSession | None:
    sessions = _get_sessions()
    return sessions[-1] if sessions else None


# ---------------------------------------------------------------------------
# LedgerSession context manager
# ---------------------------------------------------------------------------

class LedgerSession:
    """Context manager returned by ``ledger.session(session_id)``."""

    def __init__(self, session_id: str, db: str | None = None) -> None:
        self.session_id = session_id
        self.actions: list[Action] = []
        # Maps Anthropic tool_use_id → Action while we await the result
        self._pending: dict[str, Action] = {}
        self._seq = 0
        self._store = None
        if db is not None:
            from ledger.store import LedgerStore  # local import avoids circular dep
            self._store = LedgerStore(db)

    # ------------------------------------------------------------------
    # Internal capture helpers (called from _patched_create)
    # ------------------------------------------------------------------

    def _on_tool_call(self, tool_use_id: str, name: str, input_: dict) -> None:
        self._seq += 1
        action = Action(
            session_id=self.session_id,
            seq=self._seq,
            tool=name,
            args=input_,
        )
        self._pending[tool_use_id] = action
        self.actions.append(action)

    def _on_tool_result(self, tool_use_id: str, content: Any) -> None:
        action = self._pending.pop(tool_use_id, None)
        if action is None:
            return
        action.result = _normalise_content(content)
        _print_action(action)
        if self._store is not None:
            self._store.write(action)

    def _flush_pending(self) -> None:
        """Print any tool calls that never received a result (e.g. on error)."""
        for action in list(self._pending.values()):
            _print_action(action)
            if self._store is not None:
                self._store.write(action)
        self._pending.clear()

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> LedgerSession:
        _get_sessions().append(self)
        _install_patch()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._flush_pending()
        _get_sessions().remove(self)
        if not _get_sessions():
            _uninstall_patch()
        if self._store is not None:
            self._store.close()
        return False  # never suppress exceptions


# ---------------------------------------------------------------------------
# Monkey-patch machinery
# ---------------------------------------------------------------------------

_original_create = None
_patched = False
_patch_lock = threading.Lock()


def _install_patch() -> None:
    global _original_create, _patched
    with _patch_lock:
        if _patched:
            return
        try:
            from anthropic.resources.messages import Messages  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "ledger requires the 'anthropic' package: pip install anthropic"
            ) from exc
        _original_create = Messages.create
        Messages.create = _patched_create  # type: ignore[method-assign]
        _patched = True


def _uninstall_patch() -> None:
    global _original_create, _patched
    with _patch_lock:
        if not _patched:
            return
        try:
            from anthropic.resources.messages import Messages  # type: ignore[import]
            Messages.create = _original_create  # type: ignore[method-assign]
        except ImportError:
            pass
        _original_create = None
        _patched = False


def _patched_create(self, *args: Any, **kwargs: Any) -> Any:
    """Replacement for Messages.create that captures tool calls / results."""
    session = _active_session()
    if session is None:
        # No active ledger session — passthrough
        return _original_create(self, *args, **kwargs)

    # ---- 1. Capture tool_results from the *incoming* messages ----------
    messages = kwargs.get("messages", [])
    for msg in messages:
        # messages can be dicts (most common) or typed objects
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                session._on_tool_result(
                    block["tool_use_id"],
                    block.get("content"),
                )

    # ---- 2. Call the real API ------------------------------------------
    response = _original_create(self, *args, **kwargs)

    # ---- 3. Capture tool_use blocks from the *response* ----------------
    if hasattr(response, "content"):
        for block in response.content:
            block_type = block.type if hasattr(block, "type") else (block.get("type") if isinstance(block, dict) else None)
            if block_type == "tool_use":
                if isinstance(block, dict):
                    session._on_tool_call(block["id"], block["name"], block.get("input", {}))
                else:
                    session._on_tool_call(block.id, block.name, block.input)

    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_content(content: Any) -> dict:
    """Convert tool result content (str | list | None) into a plain dict."""
    if content is None:
        return {}
    if isinstance(content, dict):
        return content
    return {"content": content}


def _print_action(action: Action) -> None:
    print(action.model_dump_json(indent=2))
