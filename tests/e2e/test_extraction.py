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

        # Side effects — checked inside the container because the mounted
        # volume is chowned to the container's hermes user (bind-mount
        # permission split on Linux runners; host cannot stat it).
        code, output = run_hermes(
            hermes_home,
            "sh",
            "-c",
            "test -d /opt/data/memory && "
            "find /opt/data/memory -name '*.md' | head -1 && "
            "test -f /opt/data/tabularius_state.json && echo STATE_OK",
        )
        assert code == 0, output
        assert "STATE_OK" in output
        assert ".md" in output

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
