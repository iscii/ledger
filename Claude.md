# CLAUDE.md — Ledger
# Read this before every session.

## What this project is
A portable Python library (pip install ledger-ai, import ledger) that
wraps any AI agent and records all tool calls as a structured, replayable
action log. Zero config — no changes to existing agent code required.
"The open-source safety harness that makes any AI agent reversible."

## PyPI
Install name: ledger-ai
Import name: import ledger
GitHub repo: ledger

## Architecture
- Stage 1: Interceptor — wraps Anthropic client, captures every tool
  call as a canonical Action. TARGET FIRST.
- Stage 2: Store — SQLite via tinydb, persists Actions
- Stage 3: Inverse registry — undo functions per tool, committed flag
  for irreversible actions
- Stage 4: CLI — sessions / show / replay / rollback / diff
- Stage 5: API — FastAPI serving session and diff endpoints
- Stage 6: UI — Vue 3 session browser and visual diff view

## Canonical Action schema — DO NOT refactor this once built
id:          uuid4 string
session_id:  str
seq:         int (1-based, order within session)
ts:          datetime (UTC)
tool:        str (tool name)
args:        dict (tool input)
result:      dict (tool result content)
reversible:  bool (default True)
inverse_id:  str | None
status:      Literal["ok", "error", "committed"]

## Tech stack
- Python 3.11+
- anthropic SDK (primary target)
- Pydantic v2 (Action schema)
- FastAPI + uvicorn (Stage 5)
- SQLite + tinydb (Stage 2)
- Click (Stage 4 CLI)
- Vue 3 + Vite (Stage 6 frontend)
- Docker Compose (deployment)
- uv (package management)

## Framework adapter order
1. Anthropic tool use ← current
2. OpenAI function calling
3. LangChain / LangGraph
(add adapters in /src/ledger/adapters/ — one file per framework)

## File structure
ledger/
  src/
    ledger/
      __init__.py        ← exports ledger.session()
      interceptor.py     ← Stage 1
      schema.py          ← Action model (Stage 2)
      store.py           ← SQLite persistence (Stage 2)
      registry.py        ← inverse registry (Stage 3)
      adapters/
        anthropic.py     ← Anthropic adapter (Stage 1)
        openai.py        ← OpenAI adapter (later)
    api/
      main.py            ← FastAPI (Stage 5)
    cli/
      main.py            ← Click CLI (Stage 4)
  frontend/              ← Vue 3 (Stage 6)
  tests/
  examples/
    demo_agent.py        ← standalone demo for launch video
  CLAUDE.md              ← this file
  pyproject.toml
  README.md
  .env.example

## Current status
Day 1 complete. Stage 1 interceptor working for Anthropic tool use.
Captures tool_use + tool_result, outputs canonical Action JSON to stdout.
Validated zero-config — agent code unchanged between standalone and wrapped runs.
Next: Stage 2 — persist Actions to SQLite (store.py).