# Backstep

> The open-source safety harness that makes any AI agent reversible.

<!-- [DEMO GIF — insert after screen recording] -->

## What it does

I watched an agent rewrite the wrong file. It was confident, fast,
and completely wrong. When I asked it to undo the change, it tried —
and missed one. There was no log, no history, no way to know what it
had actually touched.

In code, we have `git`. Outside of code — in databases, APIs,
filesystems, and the systems we're increasingly handing to agents —
we have nothing. Asking an agent to undo its own changes isn't a
safety strategy. It's a guess.

Backstep gives agents a git-style action log. Every tool call is
recorded as a structured, replayable entry — what was called, with
what arguments, and what came back. You can inspect it, replay it
without the LLM, roll it back step by step, or diff two runs to see
exactly what changed.
```python
import backstep

with backstep.session("my-session"):
    result = my_existing_agent.run(client, "do a task")

# Every tool call captured. Nothing changed in your agent.
```

## Features

- **Zero config** — wrap existing agents with one context manager
- **Session logging** — every tool call recorded with full args + results
- **Deterministic replay** — re-execute sessions without the LLM
- **Rollback** — undo reversible actions via registered inverses
- **Session diff** — compare two runs to see exactly what changed
- **Plugin system** — `pip install backstep-slack` adds Slack inverses
- **REST API** — FastAPI backend for programmatic access
- **Visual UI** — browser-based session browser and diff viewer

## Why Backstep?

Most observability tools stop at showing you what happened. Rubrik's
Agent Rewind goes further — actual rollback, causality tracing,
selective undo — but it's enterprise infrastructure built for Fortune
500 security teams. There's nothing in between for developers who
just need their agent to be recoverable.

Backstep fills that gap. It's a Python library — `pip install
backstep`, one context manager, no infrastructure. The mechanism
underneath isn't new: IBM Research demonstrated at NeurIPS 2025 that
agents with undo-and-retry outperformed state-of-the-art systems by
150%+ on cloud engineering benchmarks. Backstep makes that mechanism
available to anyone building with agents today.

## Quick start

### pip install
```bash
pip install backstep
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
```

### Docker
```bash
git clone https://github.com/iscii/backstep
cd backstep
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
docker compose up
# Frontend: http://localhost:3000
# API:      http://localhost:7842
```

### Run the demo
```bash
uv run python examples/demo_agent.py
```

The demo creates a small workspace, runs an agent, deletes all files
to simulate a disaster, replays the session to restore them, then
diffs two different runs side by side.

## Usage

### Wrapping an agent
```python
import anthropic
import backstep

client = anthropic.Anthropic()

with backstep.session("my-session", db="./backstep.db"):
    # Your existing agent runs unchanged inside this block.
    # Every tool call is captured automatically.
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        tools=[...],
        messages=[{"role": "user", "content": "do a task"}],
    )
```

### Registering inverses

Inverses let Backstep undo a tool call. File operations are registered
automatically. Register your own for any custom tool:
```python
import backstep

@backstep.register_inverse("send_notification")
def undo_send_notification(args: dict, result: dict) -> None:
    # Called during rollback to reverse this tool's side-effect.
    cancel_notification(args["notification_id"])
```

### Marking committed actions

Some actions cannot be undone (emails sent, payments processed). Mark
them so rollback skips them cleanly instead of failing:
```python
@backstep.committed("charge_card")
def charge_card_tool(args: dict, result: dict) -> None:
    pass  # body unused — the decorator registers the intent
```

### CLI reference
```
backstep sessions                 List all recorded sessions
backstep show <id>                Show action timeline for a session
backstep replay <id>              Re-execute tools without the LLM
backstep rollback <id>            Undo reversible actions via inverses
backstep diff <id-a> <id-b>       Compare two sessions action by action
backstep plugins                  List loaded inverse/adapter plugins
```

All commands accept `--db <path>` to point at a non-default database,
or read the `BACKSTEP_DB` environment variable.

## Plugin system

Backstep discovers plugins automatically. Any installed package named
`backstep-*` is imported on startup. Packages can also declare entry
points under `backstep.inverses`, `backstep.adapters`, or
`backstep.reporters`.
```bash
pip install backstep-slack    # adds Slack message inverses
pip install backstep-openai   # adds OpenAI function-calling adapter
```

See [PLUGINS.md](PLUGINS.md) for how to write your own plugin.

## Architecture

Backstep is built in six stages, each independently usable:

| Stage | Name | Source | What it does |
|-------|------|--------|--------------|
| 1 | Interceptor | `src/backstep/interceptor.py` | Wraps the Anthropic client to capture every tool call as a canonical `Action` |
| 2 | Store | `src/backstep/store.py` | Persists `Action` objects to SQLite |
| 3 | Inverse registry | `src/backstep/registry.py` | Maps tool names to undo functions; tracks committed (irreversible) tools |
| 4 | CLI | `src/backstep/cli.py` | `sessions` / `show` / `replay` / `rollback` / `diff` |
| 5 | API | `src/backstep/api/main.py` | FastAPI endpoints consumed by the UI |
| 6 | UI | `frontend/` | Vue 3 session browser with visual diff view |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) to get started. Good first
issues are labelled in the tracker — no contribution is too small.

## Research

Backstep implements the undo-and-retry mechanism described in
[STRATUS (IBM Research, NeurIPS 2025)](https://research.ibm.com/blog/undo-agent-for-cloud),
which demonstrated 150%+ performance improvement on cloud engineering
benchmarks by giving agents the ability to reverse unsuccessful
actions.

## License

AGPL-3.0 — see [LICENSE](LICENSE).

---

Built by [@iscii](https://github.com/iscii)
