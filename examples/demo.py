"""
examples/demo.py
~~~~~~~~~~~~~~~~
End-to-end demo of backstep — the launch video script.

Story
-----
1. An agent runs and writes a real file to disk.
2. We show the session via the CLI.
3. We delete the file manually — simulating an accident.
4. We use `backstep replay` to restore it. No LLM call.
5. We use `backstep rollback` to undo it again.

Usage
-----
    uv run python examples/demo.py

Requires ANTHROPIC_API_KEY in .env or the environment.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import anthropic
from dotenv import load_dotenv

import backstep
from backstep.tool_registry import tool_registry

load_dotenv()

# ---------------------------------------------------------------------------
# Work directory — all demo files live here
# ---------------------------------------------------------------------------

WORK_DIR = Path(tempfile.mkdtemp(prefix="backstep_demo_"))
DB_PATH  = str(WORK_DIR / "demo.db")

# Seed a source file the agent will read
(WORK_DIR / "config.txt").write_text("debug=true\nport=8080\n")

# ---------------------------------------------------------------------------
# A plain Anthropic agent — real filesystem operations, no backstep knowledge
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "read_file",
        "description": "Return the contents of a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
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


def _read_file(path: str) -> str:
    try:
        return Path(path).read_text()
    except FileNotFoundError:
        return f"error: {path} not found"


def _write_file(path: str, content: str) -> str:
    Path(path).write_text(content)
    return "ok"


def _list_dir(path: str) -> str:
    return "\n".join(p.name for p in Path(path).iterdir())


def simple_agent(client: anthropic.Anthropic, prompt: str) -> str:
    """A plain agent. No backstep imports, no backstep knowledge."""
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

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            name, args = block.name, block.input
            if name == "read_file":
                result = _read_file(args["path"])
            elif name == "write_file":
                result = _write_file(args["path"], args["content"])
            elif name == "list_dir":
                result = _list_dir(args["path"])
            else:
                result = f"unknown tool: {name}"

            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": result}
            )

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})


# ---------------------------------------------------------------------------
# Register tool callables for replay
# ---------------------------------------------------------------------------

tool_registry.register("read_file",  lambda path: _read_file(path))
tool_registry.register("write_file", lambda path, content: _write_file(path, content))
tool_registry.register("list_dir",   lambda path: _list_dir(path))


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Set ANTHROPIC_API_KEY and try again.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    session_id = "demo-launch-01"
    out_file   = WORK_DIR / "summary.txt"

    from click.testing import CliRunner
    from backstep.cli import cli as _cli_group

    runner = CliRunner(mix_stderr=False)

    def _cli(*args: str) -> None:
        print(f"\n$ backstep {' '.join(args)}")
        print("─" * 60)
        r = runner.invoke(_cli_group, [*args, "--db", DB_PATH], catch_exceptions=False)
        print(r.output, end="")

    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("STEP 1 — Run the agent (wrapped with backstep)")
    print("=" * 60)

    with backstep.session(session_id, db=DB_PATH):
        simple_agent(
            client,
            f"List the files in {WORK_DIR}, read {WORK_DIR / 'config.txt'}, "
            f"then write a one-line summary to {out_file}.",
        )

    print(f"\n✓ Agent finished. {out_file.name} exists: {out_file.exists()}")
    if out_file.exists():
        print(f"  Contents: {out_file.read_text().strip()!r}")

    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("STEP 2 — Inspect the session via CLI")
    print("=" * 60)

    _cli("sessions")
    _cli("show", session_id)

    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("STEP 3 — Simulate an accident: delete the file")
    print("=" * 60)

    out_file.unlink(missing_ok=True)
    print(f"\n✗ Manually deleted {out_file.name}. Exists: {out_file.exists()}")

    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("STEP 4 — Replay the session (no LLM call)")
    print("=" * 60)

    _cli("replay", session_id)
    print(f"\n✓ {out_file.name} restored: {out_file.exists()}")

    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("STEP 5 — Rollback the session (undo via inverses)")
    print("=" * 60)

    _cli("rollback", session_id)
    print(f"\n✓ After rollback — {out_file.name} exists: {out_file.exists()}")

    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)
    print(f"Work dir: {WORK_DIR}")
    print(f"Database: {DB_PATH}")
    print()


if __name__ == "__main__":
    main()
