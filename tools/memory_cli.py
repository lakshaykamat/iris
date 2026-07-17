"""Read-only CLI to inspect the agent's memory fast.

Talks straight to data/agent.db (no Telegram/OpenAI env needed), so you can peek
at what she remembers, thinks, and plans without writing SQL.

Usage (from the project root):

    python -m tools.memory_cli                 # a one-screen summary of everything
    python -m tools.memory_cli chat            # recent conversation (short-term)
    python -m tools.memory_cli facts           # durable truths she knows
    python -m tools.memory_cli memories         # episodic events + reflections
    python -m tools.memory_cli schedule        # planned proactive check-ins
    python -m tools.memory_cli decisions       # why she sent / stayed silent
    python -m tools.memory_cli search aarav    # any row whose text matches

Handy flags:  -n/--limit N (rows to show),  --db PATH (point at another db).
"""

import argparse
import sqlite3
from pathlib import Path

# The db lives at <project root>/data/agent.db regardless of where you run from.
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "agent.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"No database at {db_path} — has the bot run yet?")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _print_rows(title: str, rows: list[sqlite3.Row], columns: list[str]) -> None:
    print(f"\n=== {title} ({len(rows)}) ===")
    if not rows:
        print("  (empty)")
        return
    widths = {c: len(c) for c in columns}
    cells = []
    for row in rows:
        cell = {c: " ".join(str(row[c]).split()) if row[c] is not None else ""
                for c in columns}
        for c in columns:
            widths[c] = min(max(widths[c], len(cell[c])), 60)
        cells.append(cell)
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    print(header)
    print("  ".join("-" * widths[c] for c in columns))
    for cell in cells:
        print("  ".join(cell[c][: widths[c]].ljust(widths[c]) for c in columns))


def cmd_chat(conn, limit):
    rows = conn.execute(
        "SELECT id, role, content, kind, ts FROM messages ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    _print_rows("messages (short-term)", list(reversed(rows)),
                ["id", "role", "content", "kind", "ts"])


def cmd_facts(conn, limit):
    rows = conn.execute(
        "SELECT id, text, source, superseded_by AS superseded, updated_at "
        "FROM facts ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    _print_rows("facts (long-term truths)", rows,
                ["id", "text", "source", "superseded", "updated_at"])


def cmd_memories(conn, limit):
    rows = conn.execute(
        "SELECT id, kind, importance, text, ts, last_recalled "
        "FROM memories ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    _print_rows("memories (events + reflections)", rows,
                ["id", "kind", "importance", "text", "ts", "last_recalled"])


def cmd_schedule(conn, limit):
    rows = conn.execute(
        "SELECT id, fire_at, reason, status FROM schedule "
        "ORDER BY fire_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    _print_rows("schedule (planned check-ins)", rows,
                ["id", "fire_at", "reason", "status"])


def cmd_decisions(conn, limit):
    rows = conn.execute(
        "SELECT id, ts, action, reason FROM decisions ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    _print_rows("decisions (send / silent / defer)", rows,
                ["id", "ts", "action", "reason"])


def cmd_search(conn, limit, term):
    like = f"%{term}%"
    facts = conn.execute(
        "SELECT id, text, source FROM facts WHERE text LIKE ? LIMIT ?", (like, limit)
    ).fetchall()
    mems = conn.execute(
        "SELECT id, kind, text FROM memories WHERE text LIKE ? LIMIT ?", (like, limit)
    ).fetchall()
    msgs = conn.execute(
        "SELECT id, role, content FROM messages WHERE content LIKE ? LIMIT ?",
        (like, limit),
    ).fetchall()
    _print_rows(f"facts matching {term!r}", facts, ["id", "text", "source"])
    _print_rows(f"memories matching {term!r}", mems, ["id", "kind", "text"])
    _print_rows(f"messages matching {term!r}", msgs, ["id", "role", "content"])


def cmd_summary(conn, limit):
    for name in ("messages", "facts", "memories", "schedule", "decisions"):
        count = conn.execute(f"SELECT COUNT(*) AS c FROM {name}").fetchone()["c"]
        print(f"  {name:<10} {count}")
    cmd_facts(conn, limit)
    cmd_memories(conn, limit)
    cmd_schedule(conn, min(limit, 5))
    cmd_decisions(conn, min(limit, 5))
    cmd_chat(conn, min(limit, 10))


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect the agent's memory db.")
    parser.add_argument("command", nargs="?", default="summary",
                        choices=["summary", "chat", "facts", "memories",
                                 "schedule", "decisions", "search"])
    parser.add_argument("term", nargs="?", help="text to match (for `search`)")
    parser.add_argument("-n", "--limit", type=int, default=20,
                        help="max rows to show (default 20)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help=f"database path (default {DEFAULT_DB})")
    args = parser.parse_args()

    conn = _connect(args.db)
    try:
        if args.command == "search":
            if not args.term:
                parser.error("`search` needs a term, e.g. `search aarav`")
            cmd_search(conn, args.limit, args.term)
        else:
            {
                "summary": cmd_summary,
                "chat": cmd_chat,
                "facts": cmd_facts,
                "memories": cmd_memories,
                "schedule": cmd_schedule,
                "decisions": cmd_decisions,
            }[args.command](conn, args.limit)
        print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
