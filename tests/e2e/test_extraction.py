"""Level 4 — full extraction pipeline (requires a real relay key).

`init --force` runs the memory agent over seeded sessions and writes
memory/*.md + tabularius_state.json. Skipped when TABULARIUS_API_KEY is
unset so the offline suite stays green without credentials.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TABULARIUS_API_KEY"),
    reason="TABULARIUS_API_KEY unset — set it to run the full extraction E2E",
)


class TestInitForceExtraction:
    def test_init_force_extracts_memory_docs(self, hermes_home, run_hermes) -> None:
        from fakes import make_state_db

        db = hermes_home / "state.db"
        make_state_db(
            db,
            [("s1", 100.0, 2)],
            [
                ("s1", "user", "hello", 1.0),
                ("s1", "assistant", "hi there", 2.0),
            ],
        )

        code, output = run_hermes(
            hermes_home,
            "hermes",
            "tabularius",
            "init",
            "--force",
            env={"TABULARIUS_API_KEY": os.environ["TABULARIUS_API_KEY"]},
            timeout=600,
        )
        assert code == 0, output
        assert "extracted 1 session(s)" in output
        assert "init complete" in output

        # Side effects on the mounted volume: memory docs + committed state.
        memory = hermes_home / "memory"
        assert memory.is_dir()
        assert any(memory.rglob("*.md")), f"no memory docs under {memory}"
        state = hermes_home / "tabularius_state.json"
        assert state.exists(), "state.json missing after extraction"
        assert "s1" in state.read_text(encoding="utf-8")

    def test_reindex_idempotent(self, hermes_home, run_hermes) -> None:
        from fakes import make_state_db

        db = hermes_home / "state.db"
        make_state_db(
            db,
            [("s1", 100.0, 2)],
            [
                ("s1", "user", "hello", 1.0),
                ("s1", "assistant", "hi there", 2.0),
            ],
        )
        env = {"TABULARIUS_API_KEY": os.environ["TABULARIUS_API_KEY"]}

        code1, out1 = run_hermes(
            hermes_home, "hermes", "tabularius", "init", "--force", env=env, timeout=600
        )
        assert code1 == 0, out1
        code2, out2 = run_hermes(
            hermes_home, "hermes", "tabularius", "reindex", env=env, timeout=600
        )
        assert code2 == 0, out2
        assert "index rebuilt" in out2
