"""Tests for state.py — tabularius_state.json persistence (issue #11)."""

from __future__ import annotations

import json

from tabularius import state


class TestStateFile:
    def test_state_path_under_hermes_home(self, memory_root) -> None:
        assert state.state_path() == memory_root.parent / "tabularius_state.json"

    def test_load_state_defaults(self, memory_root) -> None:
        s = state.load_state()
        assert s == {
            "committed_sessions": {},
            "last_reindex": None,
            "extraction_stats": {},
        }

    def test_save_state_roundtrip(self, memory_root) -> None:
        state.save_state(
            {"committed_sessions": {"s1": "ts"}, "last_reindex": None, "extraction_stats": {}}
        )
        assert state.load_state()["committed_sessions"] == {"s1": "ts"}

    def test_corrupt_state_falls_back_to_default(self, memory_root) -> None:
        state.state_path().write_text("{not json", encoding="utf-8")
        assert state.load_state()["committed_sessions"] == {}


class TestCommittedSessions:
    def test_mark_and_check(self, memory_root) -> None:
        assert not state.is_session_committed("s1")
        state.mark_session_committed("s1")
        assert state.is_session_committed("s1")
        assert state.committed_sessions() == {"s1": state.committed_sessions()["s1"]}

    def test_record_extraction_sets_stats(self, memory_root) -> None:
        state.record_extraction("s1", {"docs": 2, "sessions": 1})
        s = state.load_state()
        assert "s1" in s["committed_sessions"]
        assert s["extraction_stats"]["s1"]["docs"] == 2
        assert "at" in s["extraction_stats"]["s1"]

    def test_record_reindex_stamps(self, memory_root) -> None:
        assert state.load_state()["last_reindex"] is None
        state.record_reindex()
        assert state.load_state()["last_reindex"] is not None


class TestLegacyProcessed:
    def test_legacy_archive_loaded(self, memory_root) -> None:
        archive = memory_root / "archive"
        archive.mkdir(parents=True)
        (archive / "processed-sessions.json").write_text(
            json.dumps({"processed_sessions": ["s1", "s2"]}), encoding="utf-8"
        )
        assert state.legacy_processed_sessions() == ["s1", "s2"]

    def test_legacy_missing_returns_empty(self, memory_root) -> None:
        assert state.legacy_processed_sessions() == []

    def test_legacy_corrupt_returns_empty(self, memory_root) -> None:
        archive = memory_root / "archive"
        archive.mkdir(parents=True)
        (archive / "processed-sessions.json").write_text("nope", encoding="utf-8")
        assert state.legacy_processed_sessions() == []
