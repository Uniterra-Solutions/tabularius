"""Hermes state.db scanning for ``tabularius init`` (issue #12).

Reads the Hermes SQLite session store **read-only** and schema-tolerantly:
missing tables/columns degrade to empty results instead of raising, so the
CLI keeps working against older or future Hermes versions.

A session is *unprocessed* when it has at least one message and its id is
absent from the committed record (``tabularius_state.json`` merged with the
legacy ``memory/archive/processed-sessions.json``).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SESSIONS_SQL = (
    "SELECT id, started_at, message_count FROM sessions"
    " WHERE message_count IS NULL OR message_count > 0"
    " ORDER BY started_at"
)
_MESSAGES_SQL = (
    "SELECT role, content, timestamp FROM messages"
    " WHERE session_id = ? AND content IS NOT NULL"
    " ORDER BY timestamp, id"
)


@dataclass(frozen=True)
class SessionRecord:
    """One session in the store."""

    id: str
    started_at: float | None = None
    message_count: int | None = None


def connect_readonly(db_path: Path | str) -> sqlite3.Connection:
    """Open the store in SQLite read-only mode (no journal/lock writes).

    ``Path.as_uri()`` percent-encodes special characters (``?``, ``#``,
    spaces) that would otherwise corrupt the ``file:`` URI.
    """
    uri = f"{Path(db_path).resolve().as_uri()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def scan_sessions(db_path: Path | str) -> list[SessionRecord]:
    """List sessions with at least one message, oldest first.

    Returns ``[]`` when the store is missing, the sessions table is absent,
    or a required column is missing (schema tolerance).
    """
    try:
        conn = connect_readonly(db_path)
    except sqlite3.Error:
        return []
    try:
        if not _table_exists(conn, "sessions"):
            return []
        try:
            rows = conn.execute(_SESSIONS_SQL).fetchall()
        except sqlite3.Error:
            return []
        records: list[SessionRecord] = []
        for row in rows:
            sid, started_at, message_count = row[0], row[1], row[2]
            if not sid:
                continue
            records.append(
                SessionRecord(
                    id=str(sid),
                    started_at=float(started_at) if started_at is not None else None,
                    message_count=int(message_count) if message_count is not None else None,
                )
            )
        return records
    finally:
        conn.close()


def find_unprocessed(
    db_path: Path | str, committed: dict[str, Any] | list[str] | set[str]
) -> list[SessionRecord]:
    """Return sessions not present in the committed record, oldest first."""
    if isinstance(committed, dict):
        known = set(committed.keys())
    else:
        known = {str(item) for item in committed}
    return [record for record in scan_sessions(db_path) if record.id not in known]


def load_transcript(db_path: Path | str, session_id: str) -> str:
    """Render one session's messages as a transcript string ('' if none)."""
    try:
        conn = connect_readonly(db_path)
    except sqlite3.Error:
        return ""
    try:
        if not _table_exists(conn, "messages"):
            return ""
        try:
            rows = conn.execute(_MESSAGES_SQL, (session_id,)).fetchall()
        except sqlite3.Error:
            return ""
        parts: list[str] = []
        for role, content, _timestamp in rows:
            if not content:
                continue
            parts.append(f"## {role}\n{content}")
        return "\n\n".join(parts)
    finally:
        conn.close()


def default_db_path() -> Path:
    """Resolve the active profile's session store (``~/.hermes/state.db``)."""
    from tabularius.tools import memory_dir

    return memory_dir().parent / "state.db"


__all__ = [
    "SessionRecord",
    "connect_readonly",
    "default_db_path",
    "find_unprocessed",
    "load_transcript",
    "scan_sessions",
]
