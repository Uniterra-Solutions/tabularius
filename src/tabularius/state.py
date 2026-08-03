"""Profile-safe state persistence for tabularius (issue #11).

All state lives in ``tabularius_state.json`` at the global Hermes home,
resolved through fabricium's ``_get_global_hermes_home()`` (honors
``HERMES_HOME``, never hardcodes ``~/.hermes``).

Shape::

    {
      "committed_sessions": {"<session_id>": "<iso timestamp>"},
      "last_reindex": "<iso timestamp>" | null,
      "extraction_stats": {"<session_id>": {"docs": n, "sessions": n, "at": "..."}}
    }

``committed_sessions`` is the cross-process idempotency record: a session
whose id is present here has already been extracted, so neither
``on_session_end`` nor ``tabularius init`` will extract it again.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from fabricium.state import _get_global_hermes_home

STATE_FILENAME = "tabularius_state.json"


def _empty_state() -> dict[str, Any]:
    """Fresh default state (fresh nested dicts — never shared/mutated)."""
    return {
        "committed_sessions": {},
        "last_reindex": None,
        "extraction_stats": {},
    }


# Serializes load-modify-save so concurrent provider writers (daemon
# extraction threads) and CLI commands never corrupt the state file.
_LOCK = threading.Lock()


def state_path() -> Path:
    """Resolve the state file path (``~/.hermes/tabularius_state.json``)."""
    return _get_global_hermes_home() / STATE_FILENAME


def load_state() -> dict[str, Any]:
    """Load state, falling back to defaults on missing/corrupt files."""
    path = state_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return _empty_state()


def save_state(state: dict[str, Any]) -> None:
    """Atomically persist ``state`` to ``tabularius_state.json``."""
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tabularius-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def committed_sessions() -> dict[str, str]:
    """Return the ``{session_id: timestamp}`` idempotency record."""
    return dict(load_state().get("committed_sessions", {}))


def is_session_committed(session_id: str) -> bool:
    return session_id in committed_sessions()


def mark_session_committed(session_id: str) -> None:
    """Record a session as extracted (thread-safe, cross-process)."""
    with _LOCK:
        state = load_state()
        state["committed_sessions"][session_id] = _now()
        save_state(state)


def record_extraction(session_id: str, stats: dict[str, Any]) -> None:
    """Store per-session extraction stats alongside the commit record."""
    with _LOCK:
        state = load_state()
        state["committed_sessions"][session_id] = _now()
        state["extraction_stats"][session_id] = {**dict(stats), "at": _now()}
        save_state(state)


def record_reindex() -> None:
    """Stamp ``last_reindex`` with the current time."""
    with _LOCK:
        state = load_state()
        state["last_reindex"] = _now()
        save_state(state)


def legacy_processed_sessions() -> list[str]:
    """Session ids recorded by the pre-state.json archive file, if present.

    ``~/.hermes/memory/archive/processed-sessions.json`` carried the
    ``{"processed_sessions": [...]}`` record from the manual pilot phase.
    ``tabularius init`` merges these so sessions the user already processed
    are not re-extracted.
    """
    archive = _get_global_hermes_home() / "memory" / "archive" / "processed-sessions.json"
    if not archive.exists():
        return []
    try:
        data = json.loads(archive.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    raw = data.get("processed_sessions", []) if isinstance(data, dict) else []
    return [str(item) for item in raw if isinstance(item, str)]


__all__ = [
    "STATE_FILENAME",
    "committed_sessions",
    "is_session_committed",
    "legacy_processed_sessions",
    "load_state",
    "mark_session_committed",
    "record_extraction",
    "record_reindex",
    "save_state",
    "state_path",
]
