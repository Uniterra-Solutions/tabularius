"""Versioned system prompts for tabularius agents (``prompts/*.md``).

Prompts live in the package ``prompts/`` directory, one file per agent
role. Each file carries an explicit version marker in its header; bump
the version whenever the behaviour of the prompt changes. Load with
:func:`load_prompt`.
"""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    """Return the raw markdown content of ``prompts/<name>.md``."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
