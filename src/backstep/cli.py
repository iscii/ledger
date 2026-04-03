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
  3. ./backstep.db (cwd-relative default)
"""

from __future__ import annotations

import json
import os
import sys
import warnings
from typing import Optional

import click

from backstep.config import get_db_path
from backstep.deps import DependencyAnalyzer
from backstep.registry import registry as _global_registry
from backstep.replay import ReplayEngine
from backstep.rollback import RollbackEngine
from backstep.store import BackstepStore


def _resolve_db(db: Optional[str]) -> str:
    """Return the database path based on priority order."""
    path = db or str(get_db_path())
    click.echo(f"[backstep] DB: {path}", err=True)
    return path


def _resolve_seqs(
    seqs: tuple[int, ...],
    from_seq: Optional[int],
    to_seq: Optional[int],
    all_seqs: list[int],
) -> Optional[list[int]]:
    """Resolve --seq / --from / --to into a sorted list, or None (= all).

    Raises UsageError if conflicting flags are supplied.
    """
    if seqs and (from_seq is not None or to_seq is not None):
        raise click.UsageError("Use either --seq or --from/--to, not both.")
    if seqs:
        return sorted(set(seqs))
    if from_seq is not None or to_seq is not None:
        lo = from_seq if from_seq is not None else (min(all_seqs) if all_seqs else 1)
        hi = to_seq   if to_seq   is not None else (max(all_seqs) if all_seqs else 1)
        return [s for s in all_seqs if lo <= s <= hi]
    return None  # all actions


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
@click.option("--db",    default=None, help="Path to SQLite database.")
@click.option("--seq",   "seqs", multiple=True, type=int,
              help="Replay only this seq (repeatable).  E.g. --seq 3 --seq 5")
@click.option("--from",  "from_seq", default=None, type=int,
              help="Replay from this seq number onwards.")
@click.option("--to",    "to_seq",   default=None, type=int,
              help="Replay up to and including this seq number.")
@click.option("--force", is_flag=True, default=False,
              help="Proceed despite non-blocking dependency warnings.")
def replay_cmd(
    session_id: str,
    db: Optional[str],
    seqs: tuple[int, ...],
    from_seq: Optional[int],
    to_seq: Optional[int],
    force: bool,
) -> None:
    """Re-execute actions in SESSION_ID without invoking the LLM.

    By default all actions are replayed.  Use --seq, --from, or --to to
    target a subset.

    \b
    Examples:
      backstep replay demo-session
      backstep replay demo-session --seq 3 --seq 5
      backstep replay demo-session --from 3
      backstep replay demo-session --from 3 --to 5
      backstep replay demo-session --to 4
    """
    store = BackstepStore(_resolve_db(db))
    actions = store.get_session(session_id)

    if not actions:
        store.close()
        click.echo(f"No actions found for session '{session_id}'.")
        return

    all_seqs = [a.seq for a in actions]
    try:
        selected = _resolve_seqs(seqs, from_seq, to_seq, all_seqs)
    except click.UsageError as e:
        store.close()
        raise e

    # --- dependency check (selective only) -----------------------------
    if selected is not None:
        analyzer = DependencyAnalyzer(actions)
        violations = analyzer.check_replay(selected)
        blocking   = [v for v in violations if v.blocking]
        warnings_  = [v for v in violations if not v.blocking]

        if blocking:
            click.echo("\nError: cannot safely replay selected actions.\n")
            click.echo("Dependency violations:")
            for v in blocking:
                click.echo(f"  Action #{v.action_seq} ({v.tool}) — {v.reason}")
            click.echo("\nOptions:")
            all_needed = sorted(set(selected) | {v.depends_on_seq for v in blocking})
            click.echo(f"  backstep replay {session_id} "
                       + " ".join(f"--seq {s}" for s in all_needed)
                       + "   (include deps)")
            lo = min(all_needed)
            click.echo(f"  backstep replay {session_id} --from {lo}   "
                       "(replay from earliest dep)")
            click.echo(f"  backstep replay {session_id}               "
                       "(replay all)")
            store.close()
            raise SystemExit(1)

        if warnings_ and not force:
            click.echo("Warning: possible dependency issue(s).")
            for v in warnings_:
                click.echo(f"  Action #{v.action_seq} ({v.tool}) — {v.reason}")
            click.echo("  Proceeding — use --force to suppress this warning.\n")

    # --- run replay ----------------------------------------------------
    label = f"selected seqs {selected}" if selected is not None else "all actions"
    click.echo(f"Replaying session {session_id} ({label})...")

    engine = ReplayEngine(store)
    result = engine.replay(session_id, seqs=selected)
    store.close()

    click.echo(f"\n✓ Done. {result.replayed} replayed, "
               f"{result.skipped} skipped, {len(result.errors)} errors.")
    for err in result.errors:
        click.echo(f"  ✗ {err}")


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------

@cli.command("rollback")
@click.argument("session_id")
@click.option("--db",    default=None, help="Path to SQLite database.")
@click.option("--seq",   "seqs", multiple=True, type=int,
              help="Roll back only this seq (repeatable).  E.g. --seq 3 --seq 5")
@click.option("--from",  "from_seq", default=None, type=int,
              help="Roll back from this seq number onwards.")
@click.option("--to",    "to_seq",   default=None, type=int,
              help="Roll back up to and including this seq number.")
@click.option("--force", is_flag=True, default=False,
              help="Proceed despite non-blocking dependency warnings.")
@click.option("--yes",   is_flag=True, default=False,
              help="Skip the confirmation prompt.")
def rollback_cmd(
    session_id: str,
    db: Optional[str],
    seqs: tuple[int, ...],
    from_seq: Optional[int],
    to_seq: Optional[int],
    force: bool,
    yes: bool,
) -> None:
    """Roll back actions in SESSION_ID using registered inverses.

    By default all actions are rolled back.  Use --seq, --from, or --to to
    target a subset.

    \b
    Examples:
      backstep rollback demo-session
      backstep rollback demo-session --seq 5 --seq 6
      backstep rollback demo-session --from 4
      backstep rollback demo-session --from 3 --to 5
      backstep rollback demo-session --yes
    """
    store = BackstepStore(_resolve_db(db))
    actions = store.get_session(session_id)

    if not actions:
        store.close()
        click.echo(f"No actions found for session '{session_id}'.")
        return

    all_seqs = [a.seq for a in actions]
    try:
        selected = _resolve_seqs(seqs, from_seq, to_seq, all_seqs)
    except click.UsageError as e:
        store.close()
        raise e

    action_map = {a.id: a for a in actions}
    engine = RollbackEngine(store, _global_registry)

    # --- dependency check (selective only) -----------------------------
    if selected is not None:
        analyzer = DependencyAnalyzer(actions)
        violations = analyzer.check_rollback(selected)
        blocking   = [v for v in violations if v.blocking]
        warnings_  = [v for v in violations if not v.blocking]

        if blocking:
            click.echo("\nError: cannot safely roll back selected actions.\n")
            click.echo("Dependency violations:")
            for v in blocking:
                click.echo(f"  Action #{v.action_seq} ({v.tool}) — {v.reason}")
            click.echo("\nOptions:")
            all_needed = sorted(
                set(selected) | {v.depends_on_seq for v in blocking}
            )
            click.echo(f"  backstep rollback {session_id} "
                       + " ".join(f"--seq {s}" for s in all_needed)
                       + "   (include affected actions)")
            hi = max(all_needed)
            click.echo(f"  backstep rollback {session_id} --from {min(selected)}  "
                       f"--to {hi}   (include full range)")
            click.echo(f"  backstep rollback {session_id}                "
                       "(roll back all)")
            store.close()
            raise SystemExit(1)

        if warnings_ and not force:
            click.echo("Warning: possible dependency issue(s).")
            for v in warnings_:
                click.echo(f"  Action #{v.action_seq} ({v.tool}) — {v.reason}")
            click.echo("  Proceeding — use --force to suppress this warning.\n")

    # --- feasibility report --------------------------------------------
    feasibility = engine.can_rollback(session_id, seqs=selected)

    click.echo(f"\nRollback feasibility for {session_id}:")
    for af in feasibility.actions:
        symbol = "✓" if af.can_rollback else "⊘"
        click.echo(f"  {symbol} #{af.seq:<3} {af.tool:<20} — {af.reason}")

    will_rb   = len(feasibility.actions_that_can_rollback)
    will_skip = len(feasibility.actions_that_cannot)
    click.echo(f"\n  {will_rb} action{'s' if will_rb != 1 else ''} will roll back. "
               f"{will_skip} will be skipped.")

    if not yes and sys.stdin.isatty():
        click.confirm("  Proceed?", default=False, abort=True)

    # --- execute rollback ----------------------------------------------
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        result = engine.rollback(session_id, seqs=selected)

    store.close()

    click.echo()
    for action_id in sorted(
        result.rolled_back, key=lambda aid: action_map[aid].seq, reverse=True
    ):
        a = action_map[action_id]
        click.echo(f"  ✓ #{a.seq} {a.tool} → undone")

    for action_id in result.skipped:
        a = action_map[action_id]
        reason = ("committed, skipped" if a.status == "committed"
                  else "no inverse registered, skipped")
        click.echo(f"  ⊘ #{a.seq} {a.tool} → {reason}")

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
    from backstep.diff import DiffEngine

    store = BackstepStore(_resolve_db(db))
    engine = DiffEngine(store)
    result = engine.diff(session_id_a, session_id_b)
    store.close()

    click.echo(f"\nDiff: {session_id_a} vs {session_id_b}")
    click.echo("─" * 50)

    if not result.actions:
        click.echo("  Both sessions are empty.")
    else:
        for d in result.actions:
            if d.kind == "same":
                click.echo(f"  = #{d.seq}  {d.tool:<16} (same)")
            elif d.kind == "changed":
                if "args" in d.changes:
                    click.echo(
                        f"  ~ #{d.seq}  {d.tool:<16} args changed: "
                        f"{json.dumps(d.changes['args']['from'])} → "
                        f"{json.dumps(d.changes['args']['to'])}"
                    )
                else:
                    click.echo(f"  ~ #{d.seq}  {d.tool:<16} result changed")
            elif d.kind == "added":
                click.echo(f"  + #{d.seq}  {d.tool:<16} (only in {session_id_b})")
            elif d.kind == "removed":
                click.echo(f"  - #{d.seq}  {d.tool:<16} (only in {session_id_a})")

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
