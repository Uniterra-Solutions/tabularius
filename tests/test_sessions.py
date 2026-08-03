"""Tests for sessions.py — schema-tolerant state.db scanning (issue #12)."""

from __future__ import annotations

import sqlite3

from fakes import make_state_db

from tabularius import sessions


class TestScanSessions:
    def test_scans_oldest_first(self, tmp_path) -> None:
        db = tmp_path / "state.db"
        make_state_db(
            db,
            [("s1", 100.0, 2), ("s2", 50.0, 5), ("s3", 200.0, 0)],
            [],
        )
        records = sessions.scan_sessions(db)
        # oldest first; s3 (message_count 0) excluded
        assert [r.id for r in records] == ["s2", "s1"]
        assert records[0].message_count == 5

    def test_missing_db_returns_empty(self, tmp_path) -> None:
        assert sessions.scan_sessions(tmp_path / "nope.db") == []

    def test_missing_table_returns_empty(self, tmp_path) -> None:
        db = tmp_path / "state.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE unrelated (x INTEGER)")
        conn.commit()
        conn.close()
        assert sessions.scan_sessions(db) == []

    def test_scan_handles_special_chars_in_db_path(self, tmp_path) -> None:
        """'#'/'?' in the db path must not corrupt the read-only file: URI."""
        weird = tmp_path / "dir#with?chars"
        weird.mkdir()
        db = weird / "state.db"
        make_state_db(db, [("s1", 100.0, 2)], [])
        records = sessions.scan_sessions(db)
        assert [r.id for r in records] == ["s1"]


class TestFindUnprocessed:
    def test_filters_committed(self, tmp_path) -> None:
        db = tmp_path / "state.db"
        make_state_db(db, [("s1", 100.0, 2), ("s2", 50.0, 5)], [])
        assert [r.id for r in sessions.find_unprocessed(db, {"s1": "ts"})] == ["s2"]
        assert [r.id for r in sessions.find_unprocessed(db, ["s1", "s2"])] == []
        assert [r.id for r in sessions.find_unprocessed(db, set())] == ["s2", "s1"]


class TestLoadTranscript:
    def test_renders_messages_in_order(self, tmp_path) -> None:
        db = tmp_path / "state.db"
        make_state_db(
            db,
            [("s1", 100.0, 2)],
            [
                ("s1", "user", "hello", 1.0),
                ("s1", "assistant", "hi there", 2.0),
                ("s1", "tool", '{"ok": true}', 3.0),
                ("s1", "assistant", None, 4.0),  # NULL content skipped
            ],
        )
        transcript = sessions.load_transcript(db, "s1")
        assert "## user\nhello" in transcript
        assert "## assistant\nhi there" in transcript
        assert '## tool\n{"ok": true}' in transcript
        assert transcript.index("hello") < transcript.index("hi there")

    def test_missing_messages_table_returns_empty(self, tmp_path) -> None:
        db = tmp_path / "state.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()
        assert sessions.load_transcript(db, "s1") == ""

    def test_missing_db_returns_empty(self, tmp_path) -> None:
        assert sessions.load_transcript(tmp_path / "nope.db", "s1") == ""
