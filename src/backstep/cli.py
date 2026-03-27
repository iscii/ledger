"""
backstep.cli
~~~~~~~~~~~~
Click-based CLI for the backstep action recorder.

Commands
--------
  backstep sessions                  — list all recorded sessions
  backstep show <session-id>         — show action timeline
  backstep replay <session-id>       — re-execute tools without LLM
  backstep rollback <session-id>     — undo side-effects via inverses
  backstep diff <session-a> <session-b> — compare two sessions

DB resolution (in priority order)
----------------------------------
  1. --db flag on any command
  2. BACKSTEP_DB environment variable
  3. ./backstep.db in the current directory
"""

from __future__ import annotations

import json
import os
import warnings
from typing import Optional

import click

from backstep.registry import registry as _global_registry
from backstep.rollback import RollbackEngine
from backstep.store import BackstepStore


def _resolve_db(db: Optional[str]) -> str:
    """Return the database path based on priority order."""
    return db or os.environ.get("BACKSTEP_DB", "./backstep.db")


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """Backstep — AI agent action recorder and rollback engine."""


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

@cli.command("sessions")
@click.option("--db", default=None, help="Path to SQLite database.")
def sessions_cmd(db: Optional[str]) -> None:
    """List all recorded sessions."""
    store = BackstepStore(_resolve_db(db))
    rows = store.list_sessions()
    store.close()

    if not rows:
        click.echo("No sessions found.")
        return

    header = f"{'SESSION ID':<28} {'ACTIONS':>7}  {'STARTED':<20}  {'LAST ACTION':<20}"
    click.echo(header)
    click.echo("─" * len(header))
    for row in rows:
        started = row["started_at"][:19].replace("T", " ")
        last = row["last_action_at"][:19].replace("T", " ")
        click.echo(
            f"{row['session_id']:<28} {row['action_count']:>7}"
            f"  {started:<20}  {last:<20}"
        )


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

@cli.command("show")
@click.argument("session_id")
@click.option("--db", default=None, help="Path to SQLite database.")
def show_cmd(session_id: str, db: Optional[str]) -> None:
    """Show the action timeline for SESSION_ID."""
    store = BackstepStore(_resolve_db(db))
    actions = store.get_session(session_id)
    store.close()

    if not actions:
        click.echo(f"No actions found for session '{session_id}'.")
        return

    click.echo(f"\nSession: {session_id}")
    click.echo("─" * 50)
    for action in actions:
        ts = action.ts.strftime("%Y-%m-%d %H:%M:%S")
        if action.status == "committed":
            badge = "  [committed]"
        elif action.reversible:
            badge = "  [reversible]"
        else:
            badge = ""

        click.echo(
            f"#{action.seq}  {action.tool:<16} {action.status:<12} {ts}{badge}"
        )
        click.echo(f"    args:   {json.dumps(action.args)}")
        click.echo(f"    result: {json.dumps(action.result)}")
        click.echo()


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------

@cli.command("replay")
@click.argument("session_id")
@click.option("--db", default=None, help="Path to SQLite database.")
def replay_cmd(session_id: str, db: Optional[str]) -> None:
    """Re-execute all actions in SESSION_ID without invoking the LLM.

    Tool functions must be registered with backstep.register_tool() before
    replay is called.  Any tool with no registered function is skipped.
    """
    from backstep.tool_registry import tool_registry  # local import — avoids circular

    store = BackstepStore(_resolve_db(db))
    actions = store.get_session(session_id)
    store.close()

    if not actions:
        click.echo(f"No actions found for session '{session_id}'.")
        return

    click.echo(f"Replaying session {session_id} ({len(actions)} actions)...")
    replayed = skipped = errors = 0

    for action in actions:
        fn = tool_registry.get(action.tool)
        if fn is None:
            click.echo(
                f"  ⚠ #{action.seq} {action.tool} → no tool registered, skipped"
            )
            skipped += 1
            continue
        try:
            fn(**action.args)
            click.echo(f"  ✓ #{action.seq} {action.tool}")
            replayed += 1
        except Exception as exc:  # noqa: BLE001
            click.echo(f"  ✗ #{action.seq} {action.tool} → error: {exc}")
            errors += 1

    click.echo(f"\nDone. {replayed} replayed, {skipped} skipped, {errors} errors.")


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------

@cli.command("rollback")
@click.argument("session_id")
@click.option("--db", default=None, help="Path to SQLite database.")
def rollback_cmd(session_id: str, db: Optional[str]) -> None:
    """Roll back all actions in SESSION_ID using registered inverses."""
    store = BackstepStore(_resolve_db(db))
    actions = store.get_session(session_id)

    if not actions:
        click.echo(f"No actions found for session '{session_id}'.")
        store.close()
        return

    click.echo(f"Rolling back session {session_id} ({len(actions)} actions)...")
    action_map = {a.id: a for a in actions}

    engine = RollbackEngine(store, _global_registry)
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        result = engine.rollback(session_id)

    store.close()

    # Report in reverse seq order (matches rollback direction)
    for action_id in sorted(
        result.rolled_back, key=lambda aid: action_map[aid].seq, reverse=True
    ):
        a = action_map[action_id]
        click.echo(f"  ✓ #{a.seq} {a.tool} → undone")

    for action_id in result.skipped:
        a = action_map[action_id]
        reason = (
            "committed, skipped"
            if a.status == "committed"
            else "no inverse registered, skipped"
        )
        click.echo(f"  ⚠ #{a.seq} {a.tool} → {reason}")

    for action_id in result.errors:
        a = action_map[action_id]
        click.echo(f"  ✗ #{a.seq} {a.tool} → error during rollback")

    click.echo(
        f"\nDone. {len(result.rolled_back)} rolled back, "
        f"{len(result.skipped)} skipped, "
        f"{len(result.errors)} errors."
    )


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

@cli.command("diff")
@click.argument("session_id_a")
@click.argument("session_id_b")
@click.option("--db", default=None, help="Path to SQLite database.")
def diff_cmd(
    session_id_a: str, session_id_b: str, db: Optional[str]
) -> None:
    """Compare two sessions action by action."""
    store = BackstepStore(_resolve_db(db))
    actions_a = store.get_session(session_id_a)
    actions_b = store.get_session(session_id_b)
    store.close()

    click.echo(f"\nDiff: {session_id_a} vs {session_id_b}")
    click.echo("─" * 50)

    if not actions_a and not actions_b:
        click.echo("  Both sessions are empty.")
    else:
        for i in range(max(len(actions_a), len(actions_b))):
            a = actions_a[i] if i < len(actions_a) else None
            b = actions_b[i] if i < len(actions_b) else None

            if a is None:
                click.echo(f"  + #{b.seq}  {b.tool:<16} (only in {session_id_b})")
            elif b is None:
                click.echo(f"  - #{a.seq}  {a.tool:<16} (only in {session_id_a})")
            elif a.tool == b.tool and a.args == b.args:
                click.echo(f"  = #{a.seq}  {a.tool:<16} (same)")
            elif a.tool != b.tool:
                click.echo(
                    f"  ~ #{a.seq}  tool changed: {a.tool} → {b.tool}"
                )
            else:
                click.echo(
                    f"  ~ #{a.seq}  {a.tool:<16} args changed: "
                    f"{json.dumps(a.args)} → {json.dumps(b.args)}"
                )

    click.echo("\nLegend: = same  ~ changed  + added  - removed")


# ---------------------------------------------------------------------------
# plugins
# ---------------------------------------------------------------------------

@cli.command("plugins")
def plugins_cmd() -> None:
    """List all loaded inverse plugins and their registered tools."""
    from backstep.registry import registry as _reg

    registered = _reg.list_registered()  # {tool_name: source_label}

    if not registered:
        click.echo("No plugins loaded.")
        return

    # Group by source label
    by_source: dict[str, list[str]] = {}
    for tool_name, source in registered.items():
        by_source.setdefault(source, []).append(tool_name)

    click.echo("Loaded plugins:")
    for source, tools in sorted(by_source.items()):
        click.echo(f"  {source}")
        click.echo(f"    inverses: {', '.join(sorted(tools))}")
