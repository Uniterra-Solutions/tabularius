"""Level 2 — CLI offline tests (no LLM key required).

status / setup / init dry-run against a seeded state.db. Verifies the CLI
surface works inside Hermes without touching the network.
"""

from __future__ import annotations

from pathlib import Path


def _seed_state_db(home: Path) -> Path:
    """Create a Hermes-shaped state.db with one unprocessed session."""
    from fakes import make_state_db

    db = home / "state.db"
    make_state_db(
        db,
        [("s1", 100.0, 2), ("s2", 50.0, 0)],
        [
            ("s1", "user", "hello", 1.0),
            ("s1", "assistant", "hi there", 2.0),
        ],
    )
    return db


class TestStatus:
    def test_status_reports_no_key(self, hermes_home, run_hermes) -> None:
        code, output = run_hermes(hermes_home, "hermes", "tabularius", "status")
        assert code == 0, output
        assert "Available:        no" in output
        assert "TABULARIUS_API_KEY" in output

    def test_status_counts_committed(self, hermes_home, run_hermes) -> None:
        # Pre-seed tabularius_state.json with a committed session.
        import json

        state = hermes_home / "tabularius_state.json"
        state.write_text(
            json.dumps({"committed_sessions": {"s1": "2026-01-01T00:00:00"}}),
            encoding="utf-8",
        )
        code, output = run_hermes(hermes_home, "hermes", "tabularius", "status")
        assert code == 0, output
        assert "Committed:        1 session(s)" in output


class TestSetup:
    def test_setup_creates_memory_dir(self, hermes_home, run_hermes) -> None:
        code, output = run_hermes(hermes_home, "hermes", "tabularius", "setup")
        assert code == 0, output
        assert "Memory directory:" in output
        # The memory dir must exist on the mounted volume after setup.
        assert (hermes_home / "memory").is_dir()


class TestInitDryRun:
    def test_init_dry_run_empty_db(self, hermes_home, run_hermes) -> None:
        code, output = run_hermes(hermes_home, "hermes", "tabularius", "init")
        assert code == 0, output
        assert "0 unprocessed session(s)" in output
        assert "DRY RUN" in output

    def test_init_dry_run_lists_unprocessed(self, hermes_home, run_hermes) -> None:
        _seed_state_db(hermes_home)
        code, output = run_hermes(hermes_home, "hermes", "tabularius", "init")
        assert code == 0, output
        assert "1 unprocessed session(s)" in output
        assert "s1" in output
        assert "DRY RUN" in output

    def test_init_force_without_key_fails_cleanly(self, hermes_home, run_hermes) -> None:
        """--force needs the LLM; without a key it must fail, not hang."""
        _seed_state_db(hermes_home)
        code, output = run_hermes(hermes_home, "hermes", "tabularius", "init", "--force")
        assert code != 0
        assert "API key" in output or "TABULARIUS_API_KEY" in output
