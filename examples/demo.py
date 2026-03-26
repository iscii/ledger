"""
examples/demo.py
~~~~~~~~~~~~~~~~
End-to-end demo of ledger wrapping a simple Anthropic agent.

Usage:
    uv run python examples/demo.py

Requires ANTHROPIC_API_KEY in a .env file or the environment.
"""

import anthropic
from dotenv import load_dotenv

import ledger
from ledger.store import LedgerStore

load_dotenv()

# ---------------------------------------------------------------------------
# A plain Anthropic agent — no knowledge of ledger
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

_FS: dict[str, str] = {"config.txt": "debug=true\nport=8080\n"}


def simple_agent(client: anthropic.Anthropic, prompt: str) -> str:
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
                result = _FS.get(args["path"], f"error: {args['path']} not found")
            elif name == "write_file":
                _FS[args["path"]] = args["content"]
                result = "ok"
            elif name == "list_dir":
                result = "\n".join(_FS.keys())
            else:
                result = f"unknown tool: {name}"
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": result}
            )

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    client = anthropic.Anthropic()

    print("=" * 60)
    print("Running agent wrapped with ledger.session(db='demo.db')")
    print("=" * 60)

    with ledger.session("demo-01", db="./demo.db") as sess:
        result = simple_agent(
            client,
            "List the files, read config.txt, write a one-line summary to out.txt.",
        )

    print(f"\nAgent returned: {result!r}")
    print(f"Captured {len(sess.actions)} action(s) in session\n")

    print("=" * 60)
    print("Querying demo.db independently via LedgerStore")
    print("=" * 60)

    store = LedgerStore("./demo.db")
    print("\nlist_sessions():", store.list_sessions())
    print("\nget_session('demo-01'):")
    for action in store.get_session("demo-01"):
        print(f"  seq={action.seq}  tool={action.tool}  result={action.result}")
    store.close()
