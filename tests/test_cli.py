"""Tests for cli.py — status/setup/update + init/reindex (issues #11, #12)."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest
from fakes import _FakeMessage, _FakeResponse, _ScriptedClient

from tabularius import cli
from tabularius import state as tabularius_state

_CREATE_OUTPUT = json.dumps(
    {
        "documents": [{"action": "create", "path": "a.md", "content": "# A\n", "reason": "r"}],
        "processed_sessions": ["sess-a", "sess-b"],
        "stats": {"docs": 1, "sessions": 2},
    }
)


def _make_db(path, session_rows, message_rows) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at REAL, message_count INTEGER)"
    )
    conn.execute(
        "CREATE TABLE messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT,"
        " content TEXT, timestamp REAL)"
    )
    for row in session_rows:
        conn.execute("INSERT INTO sessions (id, started_at, message_count) VALUES (?,?,?)", row)
    for row in message_rows:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?,?,?,?)", row
        )
    conn.commit()
    conn.close()


def _db_with_two_sessions(memory_root) -> str:
    db = memory_root.parent / "state.db"
    _make_db(
        db,
        [("sess-a", 100.0, 2), ("sess-b", 200.0, 2)],
        [
            ("sess-a", "user", "hello a", 1.0),
            ("sess-a", "assistant", "hi a", 2.0),
            ("sess-b", "user", "hello b", 1.0),
            ("sess-b", "assistant", "hi b", 2.0),
        ],
    )
    return str(db)


def _parse(argv: list[str]) -> SimpleNamespace:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers()
    subparser = subs.add_parser("tabularius")
    cli.register_cli(subparser)
    args = parser.parse_args(["tabularius", *argv])
    return SimpleNamespace(
        tabularius_command=args.tabularius_command,
        force=getattr(args, "force", False),
        db=getattr(args, "db", None),
        check=getattr(args, "check", False),
        git=getattr(args, "git", False),
        pip=getattr(args, "pip", False),
    )


class TestRegisterCli:
    def test_builds_subcommands(self) -> None:
        for command in ("status", "setup", "update", "init", "reindex"):
            args = _parse([command])
            assert args.tabularius_command == command

    def test_init_flags(self, memory_root) -> None:
        args = _parse(["init", "--force", "--db", "/tmp/x.db"])
        assert args.force is True
        assert args.db == "/tmp/x.db"
        assert _parse(["init"]).force is False

    def test_update_check_flag(self) -> None:
        assert _parse(["update", "--check"]).check is True

    def test_unknown_subcommand_exits(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            cli.tabularius_command(SimpleNamespace(tabularius_command="bogus"))
        assert exc.value.code == 2


class TestStatus:
    def test_status_shows_provider_and_state(self, memory_root, capsys, monkeypatch) -> None:
        monkeypatch.setenv("TABULARIUS_API_KEY", "test-key")
        tabularius_state.record_extraction("s1", {"docs": 1, "sessions": 1})
        tabularius_state.record_reindex()

        cli.cmd_status(SimpleNamespace(tabularius_command="status"))
        out = capsys.readouterr().out
        assert "Provider:         tabularius" in out
        assert "Available:        yes" in out
        assert "Committed:        1 session(s)" in out
        assert "Last extraction:" in out
        assert "Last reindex:" in out

    def test_status_reports_missing_key(self, memory_root, capsys, monkeypatch) -> None:
        monkeypatch.delenv("TABULARIUS_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cli.cmd_status(SimpleNamespace(tabularius_command="status"))
        out = capsys.readouterr().out
        assert "Available:        no" in out


class TestSetup:
    def test_setup_activates_via_hermes_config(self, memory_root, capsys, monkeypatch) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr("tabularius.cli.subprocess.run", fake_run)
        cli.cmd_setup(SimpleNamespace(tabularius_command="setup"))
        out = capsys.readouterr().out
        assert "Memory directory" in out
        assert "memory.provider = tabularius" in out
        assert calls == [["hermes", "config", "set", "memory.provider", "tabularius"]]
        assert memory_root.is_dir()

    def test_setup_fallback_instructions(self, memory_root, capsys, monkeypatch) -> None:
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("no hermes")

        monkeypatch.setattr("tabularius.cli.subprocess.run", fake_run)
        cli.cmd_setup(SimpleNamespace(tabularius_command="setup"))
        out = capsys.readouterr().out
        assert "Run manually: hermes config set memory.provider tabularius" in out


class TestInitDryRun:
    def test_dry_run_reports_only(self, memory_root, capsys) -> None:
        db = _db_with_two_sessions(memory_root)
        args = SimpleNamespace(tabularius_command="init", force=False, db=db)

        assert cli.cmd_init(args) == 0
        out = capsys.readouterr().out
        assert "2 unprocessed session(s)" in out
        assert "DRY RUN" in out
        assert "sess-a" in out
        assert "sess-b" in out
        assert "1 extraction batch(es)" in out

        # nothing executed
        assert not (memory_root / "a.md").exists()
        assert not (memory_root.parent / "tabularius_state.json").exists()

    def test_dry_run_merges_legacy_processed(self, memory_root, capsys) -> None:
        archive = memory_root / "archive"
        archive.mkdir(parents=True)
        (archive / "processed-sessions.json").write_text(
            json.dumps({"processed_sessions": ["sess-a"]}), encoding="utf-8"
        )
        db = _db_with_two_sessions(memory_root)
        args = SimpleNamespace(tabularius_command="init", force=False, db=db)

        cli.cmd_init(args)
        out = capsys.readouterr().out
        assert "1 unprocessed session(s)" in out
        assert "sess-b" in out
        assert "sess-a" not in out


class TestInitForce:
    def test_full_migration(self, memory_root, capsys, monkeypatch) -> None:
        memories = memory_root.parent / "memories"
        memories.mkdir()
        (memories / "MEMORY.md").write_text("old memory entry\n", encoding="utf-8")
        (memories / "USER.md").write_text("user profile stuff\n", encoding="utf-8")

        db = _db_with_two_sessions(memory_root)
        client = _ScriptedClient([_FakeResponse(_FakeMessage(_CREATE_OUTPUT))])
        index_calls: list[int] = []

        def fake_index(client=None, reader_client=None) -> None:
            index_calls.append(1)

        monkeypatch.setattr("tabularius.cli.run_index_agent", fake_index)
        args = SimpleNamespace(tabularius_command="init", force=True, db=db)

        assert cli.cmd_init(args, client=client) == 0  # type: ignore[arg-type]
        out = capsys.readouterr().out
        assert "Backed up memory entries" in out
        assert "extracted 2 session(s)" in out
        assert "init complete" in out

        # backup archived before any clearing
        backups = list((memory_root / "archive").glob("pre-init-*.json"))
        assert len(backups) == 1
        payload = json.loads(backups[0].read_text(encoding="utf-8"))
        assert payload["memory_raw"] == "old memory entry\n"
        assert payload["user_raw"] == "user profile stuff\n"

        # extraction wrote the document and recorded commits
        assert (memory_root / "a.md").read_text(encoding="utf-8") == "# A\n"
        s = tabularius_state.load_state()
        assert set(s["committed_sessions"]) == {"sess-a", "sess-b"}
        assert s["last_reindex"] is not None
        assert index_calls == [1]

        # MEMORY.md switched to pointer; USER.md untouched
        assert (memories / "MEMORY.md").read_text(encoding="utf-8") == (
            "Memory → see ~/.hermes/memory/INDEX.md\n"
        )
        assert (memories / "USER.md").read_text(encoding="utf-8") == "user profile stuff\n"

    def test_force_with_no_sessions_still_switchover(
        self, memory_root, capsys, monkeypatch
    ) -> None:
        memories = memory_root.parent / "memories"
        memories.mkdir()
        (memories / "MEMORY.md").write_text("old\n", encoding="utf-8")

        db = memory_root.parent / "state.db"
        _make_db(db, [], [])
        monkeypatch.setattr("tabularius.cli.run_index_agent", lambda **kw: None)
        args = SimpleNamespace(tabularius_command="init", force=True, db=str(db))

        cli.cmd_init(args)
        out = capsys.readouterr().out
        assert "0 unprocessed session(s)" in out
        assert (memories / "MEMORY.md").read_text(encoding="utf-8") == (
            "Memory → see ~/.hermes/memory/INDEX.md\n"
        )
        assert list((memory_root / "archive").glob("pre-init-*.json"))


class TestReindex:
    def test_reindex_runs_index_agent_and_stamps(self, memory_root, capsys, monkeypatch) -> None:
        index_calls: list[int] = []

        def fake_index(client=None, reader_client=None) -> None:
            index_calls.append(1)

        monkeypatch.setattr("tabularius.cli.run_index_agent", fake_index)
        args = SimpleNamespace(tabularius_command="reindex")

        assert cli.cmd_reindex(args) == 0
        assert index_calls == [1]
        assert tabularius_state.load_state()["last_reindex"] is not None


class TestSwitchoverHelpers:
    def test_backup_memory_entries(self, memory_root) -> None:
        memories = memory_root.parent / "memories"
        memories.mkdir()
        (memories / "MEMORY.md").write_text("m1\n", encoding="utf-8")
        (memories / "USER.md").write_text("u1\n", encoding="utf-8")

        path = cli.backup_memory_entries()
        assert path.parent == memory_root / "archive"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["memory_raw"] == "m1\n"
        assert payload["user_raw"] == "u1\n"

    def test_clear_memory_file_keeps_user(self, memory_root) -> None:
        memories = memory_root.parent / "memories"
        memories.mkdir()
        (memories / "USER.md").write_text("keep me\n", encoding="utf-8")

        target = cli.clear_memory_file()
        assert target.read_text(encoding="utf-8") == ("Memory → see ~/.hermes/memory/INDEX.md\n")
        assert (memories / "USER.md").read_text(encoding="utf-8") == "keep me\n"
