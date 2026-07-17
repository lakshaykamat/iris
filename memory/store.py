"""SQLite access layer — the single source of truth for all persisted state."""

import sqlite3
from pathlib import Path

# How every timestamp is stored: UTC, second precision. Fixed width so the
# strings sort chronologically and can be compared directly in SQL.
TS_FORMAT = "%Y-%m-%d %H:%M:%S"

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    role    TEXT NOT NULL,
    content TEXT NOT NULL,
    kind    TEXT NOT NULL DEFAULT 'text',
    ts      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS facts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    text          TEXT NOT NULL,
    source        TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_by INTEGER REFERENCES facts(id)
);

CREATE TABLE IF NOT EXISTS memories (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    text          TEXT NOT NULL,
    kind          TEXT NOT NULL,
    importance    INTEGER NOT NULL,
    ts            TEXT NOT NULL DEFAULT (datetime('now')),
    last_recalled TEXT
);

CREATE TABLE IF NOT EXISTS schedule (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    fire_at TEXT NOT NULL,
    reason  TEXT NOT NULL,
    status  TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS decisions (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL DEFAULT (datetime('now')),
    action TEXT NOT NULL,
    reason TEXT
);
"""


class Store:
    """Thin wrapper over the SQLite connection holding the agent's state."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        try:
            self.conn.execute(
                "ALTER TABLE schedule ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
            )
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    def save_message(self, role: str, content: str, kind: str = "text") -> None:
        self.conn.execute(
            "INSERT INTO messages (role, content, kind) VALUES (?, ?, ?)",
            (role, content, kind),
        )
        self.conn.commit()

    def recent_messages(self, limit: int) -> list[sqlite3.Row]:
        """Return the last `limit` messages in chronological order."""
        rows = self.conn.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return list(reversed(rows))

    # --- Facts: durable truths that can be corrected over time ---------------

    def save_fact(self, text: str, source: str | None = None) -> int:
        cursor = self.conn.execute(
            "INSERT INTO facts (text, source) VALUES (?, ?)",
            (text, source),
        )
        self.conn.commit()
        return cursor.lastrowid

    def active_facts(self) -> list[sqlite3.Row]:
        """Return facts that have not been superseded, oldest first."""
        return self.conn.execute(
            "SELECT id, text FROM facts WHERE superseded_by IS NULL ORDER BY id"
        ).fetchall()

    def supersede_fact(self, old_id: int, text: str, source: str | None = None) -> int:
        """Replace an existing fact with a corrected one, keeping the old row."""
        new_id = self.save_fact(text, source)
        self.conn.execute(
            "UPDATE facts SET superseded_by = ?, updated_at = datetime('now') WHERE id = ?",
            (new_id, old_id),
        )
        self.conn.commit()
        return new_id

    # --- Memories: the episodic stream + distilled reflections --------------

    def save_memory(self, text: str, kind: str, importance: int) -> int:
        cursor = self.conn.execute(
            "INSERT INTO memories (text, kind, importance) VALUES (?, ?, ?)",
            (text, kind, importance),
        )
        self.conn.commit()
        return cursor.lastrowid

    def all_memories(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT id, text, kind, importance, ts, last_recalled FROM memories"
        ).fetchall()

    def bump_recalled(self, ids: list[int]) -> None:
        """Mark memories as recalled now, so recency reflects real use."""
        if not ids:
            return
        self.conn.executemany(
            "UPDATE memories SET last_recalled = datetime('now') WHERE id = ?",
            [(mid,) for mid in ids],
        )
        self.conn.commit()

    def events_since(self, ts: str | None) -> list[sqlite3.Row]:
        """Return episodic events recorded after `ts` (all events if None)."""
        if ts is None:
            return self.conn.execute(
                "SELECT id, text, ts FROM memories WHERE kind = 'event' ORDER BY id"
            ).fetchall()
        return self.conn.execute(
            "SELECT id, text, ts FROM memories WHERE kind = 'event' AND ts > ? ORDER BY id",
            (ts,),
        ).fetchall()

    def last_reflection_ts(self) -> str | None:
        row = self.conn.execute(
            "SELECT MAX(ts) AS ts FROM memories WHERE kind = 'reflection'"
        ).fetchone()
        return row["ts"] if row else None

    # --- Schedule: the self-planned check-ins that drive proactivity --------

    def add_checkin(self, fire_at: str, reason: str) -> int:
        cursor = self.conn.execute(
            "INSERT INTO schedule (fire_at, reason) VALUES (?, ?)",
            (fire_at, reason),
        )
        self.conn.commit()
        return cursor.lastrowid

    def add_reminder(self, fire_at: str, reason: str) -> int:
        """Like add_checkin but pinned=1 — the gate and presence checks are skipped."""
        cursor = self.conn.execute(
            "INSERT INTO schedule (fire_at, reason, pinned) VALUES (?, ?, 1)",
            (fire_at, reason),
        )
        self.conn.commit()
        return cursor.lastrowid

    def next_pending_checkin(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT id, fire_at, reason, pinned FROM schedule "
            "WHERE status = 'pending' ORDER BY fire_at LIMIT 1"
        ).fetchone()

    def mark_checkin_done(self, checkin_id: int) -> None:
        self.conn.execute(
            "UPDATE schedule SET status = 'done' WHERE id = ?", (checkin_id,)
        )
        self.conn.commit()

    def reschedule_checkin(self, checkin_id: int, fire_at: str) -> None:
        self.conn.execute(
            "UPDATE schedule SET fire_at = ? WHERE id = ?", (fire_at, checkin_id)
        )
        self.conn.commit()

    # --- Decisions: an audit trail of why she sent or stayed silent --------

    def log_decision(self, action: str, reason: str) -> None:
        self.conn.execute(
            "INSERT INTO decisions (action, reason) VALUES (?, ?)", (action, reason)
        )
        self.conn.commit()

    def last_user_message_ts(self) -> str | None:
        row = self.conn.execute(
            "SELECT MAX(ts) AS ts FROM messages WHERE role = 'user'"
        ).fetchone()
        return row["ts"] if row else None

    def last_assistant_message_ts(self) -> str | None:
        row = self.conn.execute(
            "SELECT MAX(ts) AS ts FROM messages WHERE role = 'assistant'"
        ).fetchone()
        return row["ts"] if row else None

    def last_message(self) -> tuple[str, str] | None:
        """Return (ts, role) of the most recent message, or None."""
        row = self.conn.execute(
            "SELECT ts, role FROM messages ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return (row["ts"], row["role"]) if row else None
