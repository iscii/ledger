"""
examples/demo_agent.py
~~~~~~~~~~~~~~~~~~~~~~
End-to-end demo of Backstep — the launch video script.

Story
-----
1.  Create a small workspace with three files.
2.  Run an Anthropic agent wrapped with backstep.session().
3.  Show the captured session via the CLI.
4.  Simulate a disaster — delete all workspace files.
5.  Replay the session to restore the files (no LLM call).
6.  Run a second agent with a slightly different task.
7.  Diff the two sessions to see exactly what changed.

Usage
-----
    uv run python examples/demo_agent.py

Requires ANTHROPIC_API_KEY in the environment or a .env file.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
import anthropic

import backstep

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT      = Path(__file__).parent.parent
WORKSPACE = ROOT / "workspace"
DB_PATH   = str(ROOT / "demo.db")

# ---------------------------------------------------------------------------
# Tool definitions (passed to the Anthropic API)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "list_dir",
        "description": "List files in a directory.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory path"}},
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Return the text contents of a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write text content to a file, creating it if needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "Text content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "delete_file",
        "description": "Delete a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path"}},
            "required": ["path"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _list_dir(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"error: {path} does not exist"
    return "\n".join(f.name for f in sorted(p.iterdir()))


def _read_file(path: str) -> str:
    try:
        return Path(path).read_text()
    except FileNotFoundError:
        return f"error: {path} not found"


def _write_file(path: str, content: str) -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content)
    return "ok"


def _delete_file(path: str) -> str:
    try:
        previous = Path(path).read_text()
        Path(path).unlink()
        return f"deleted (previous content: {previous[:80]})"
    except FileNotFoundError:
        return f"error: {path} not found"


def _dispatch(name: str, args: dict) -> str:
    if name == "list_dir":
        return _list_dir(args["path"])
    if name == "read_file":
        return _read_file(args["path"])
    if name == "write_file":
        return _write_file(args["path"], args["content"])
    if name == "delete_file":
        return _delete_file(args["path"])
    return f"unknown tool: {name}"

# Register tools for deterministic replay (no LLM needed)
backstep.register_tool("list_dir")(lambda path: _list_dir(path))
backstep.register_tool("read_file")(lambda path: _read_file(path))
backstep.register_tool("write_file")(lambda path, content: _write_file(path, content))
backstep.register_tool("delete_file")(lambda path: _delete_file(path))

# ---------------------------------------------------------------------------
# Simple agent loop
# ---------------------------------------------------------------------------

def run_agent(client: anthropic.Anthropic, task: str) -> str:
    """Run a tool-use loop until the model finishes. Returns final text."""
    messages: list[dict] = [{"role": "user", "content": task}]

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
            result = _dispatch(block.name, block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user",      "content": tool_results})

# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------

def cli(*args: str) -> None:
    """Run a backstep CLI command and print its output."""
    cmd = ["uv", "run", "backstep", *args, "--db", DB_PATH]
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        print(f"  [CLI exited with code {result.returncode}]")

# ---------------------------------------------------------------------------
# Section header helper
# ---------------------------------------------------------------------------

def section(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)

# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set.")
        print("  Add it to .env or export it in your shell.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # ------------------------------------------------------------------ 1
    section("STEP 1 — Creating workspace")

    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)
    WORKSPACE.mkdir()

    (WORKSPACE / "config.json").write_text('{"debug": true, "port": 8080}\n')
    (WORKSPACE / "notes.txt").write_text("TODO: update deployment config\n")
    (WORKSPACE / "README.md").write_text("# My Project\n")

    print(f"  Created {WORKSPACE}/")
    for f in sorted(WORKSPACE.iterdir()):
        print(f"    {f.name}")

    # ------------------------------------------------------------------ 2
    section("STEP 2 — Running agent (session: demo-session)")

    task_1 = (
        f"List the files in {WORKSPACE}, "
        f"read config.json and notes.txt, "
        f"write a one-line summary to {WORKSPACE}/summary.txt, "
        f"and update {WORKSPACE}/config.json to set debug to false."
    )

    with backstep.session("demo-session", db=DB_PATH):
        run_agent(client, task_1)

    print()
    print("  Agent finished.")

    # ------------------------------------------------------------------ 3
    section("STEP 3 — Backstep captured the session")
    cli("show", "demo-session")

    # ------------------------------------------------------------------ 4
    section("STEP 4 — Simulating disaster — deleting workspace files")

    for f in list(WORKSPACE.iterdir()):
        f.unlink()
        print(f"  Deleted {f.name}")

    print()
    print(f"  Files remaining: {list(WORKSPACE.iterdir())}")

    # ------------------------------------------------------------------ 5
    section("STEP 5 — Replaying session — no LLM required")
    cli("replay", "demo-session")

    # ------------------------------------------------------------------ 6
    section("STEP 6 — Files restored")

    restored = sorted(WORKSPACE.iterdir())
    for f in restored:
        print(f"  {f.name}")

    if not restored:
        print("  [Warning: no files found — replay may have failed]")

    # ------------------------------------------------------------------ 7
    section("STEP 7 — Running second agent (session: demo-session-2)")

    task_2 = (
        f"List the files in {WORKSPACE}, "
        f"read config.json and notes.txt, "
        f"write a one-line summary to {WORKSPACE}/summary.txt "
        f"but keep debug as true in config.json."
    )

    with backstep.session("demo-session-2", db=DB_PATH):
        run_agent(client, task_2)

    print()
    print("  Agent finished.")

    # ------------------------------------------------------------------ 8
    section("STEP 8 — Diffing demo-session vs demo-session-2")
    cli("diff", "demo-session", "demo-session-2")

    # ------------------------------------------------------------------ 9
    section("DONE")
    print("  Open http://localhost:7842 to explore sessions via the API.")
    print("  Or run:  make up  then open http://localhost:3000 for the UI.")
    print()
    print(f"  Database: {DB_PATH}")
    print()


if __name__ == "__main__":
    main()
