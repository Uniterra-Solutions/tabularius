"""Hand-written tools for tabularius agents.

All tools operate on the profile-safe memory directory
(``~/.hermes/memory/``, resolved via fabricium's
``_get_global_hermes_home()``). Every tool returns a JSON string in
OpenAI function-calling format: ``{"ok": true, ...}`` on success and
``{"ok": false, "error": "..."}`` on failure.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from fabricium.state import _get_global_hermes_home

from tabularius.llm import LLMClient
from tabularius.schemas import IndexEntry, ReaderAgentOutput

MEMORY_DIR_NAME = "memory"
INDEX_FILE = "INDEX.md"

READER_SYSTEM_PROMPT = (
    "You are the Tabularius reader agent. Read the memory document below and "
    "return JSON with:\n"
    '- "path": the document path,\n'
    '- "summary": a concise 2-3 sentence summary in the document\'s language,\n'
    '- "key_topics": 3-6 short topic strings,\n'
    '- "category_hint": a suggested category filename stem (lowercase-hyphens).\n'
)


class ToolError(ValueError):
    """Raised when a tool precondition fails (unsafe path, missing file)."""


def memory_dir() -> Path:
    """Resolve the profile-safe memory directory (``~/.hermes/memory/``)."""
    return _get_global_hermes_home() / MEMORY_DIR_NAME


def _resolve_path(name: str) -> Path:
    """Resolve a memory-relative path, rejecting traversal outside the root."""
    root = memory_dir().resolve()
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root):
        raise ToolError(f"path escapes memory directory: {name}")
    return candidate


def _atomic_write(target: Path, content: str) -> None:
    """Write ``content`` to ``target`` atomically (tmp file + os.replace)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=target.parent, prefix=".tabularius-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _ok(**data: Any) -> str:
    return json.dumps({"ok": True, **data}, ensure_ascii=False)


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


# ── Tools ────────────────────────────────────────────────────────────────────


def memory_read(path: str) -> str:
    """Read a single .md file. Returns content or an explicit error."""
    try:
        target = _resolve_path(path)
    except ToolError as exc:
        return _err(str(exc))
    if not target.is_file():
        return _err(f"file not found: {path}")
    return _ok(path=path, content=target.read_text(encoding="utf-8"))


def memory_write(path: str, content: str, action: str) -> str:
    """Merge-write a memory document (atomic).

    ``action="create"`` requires the file to NOT exist (refuses to
    overwrite existing content); ``action="merge"`` requires it to exist
    — the agent must have read the current file first and provide the
    final complete content here. The tool layer only writes atomically;
    it never merges or silently overwrites.
    """
    if action not in ("create", "merge"):
        return _err(f"invalid action: {action} (expected 'create' or 'merge')")
    try:
        target = _resolve_path(path)
    except ToolError as exc:
        return _err(str(exc))
    exists = target.is_file()
    if action == "create" and exists:
        return _err(f"refusing to overwrite existing file: {path} (use action='merge')")
    if action == "merge" and not exists:
        return _err(f"file does not exist: {path} (use action='create')")
    _atomic_write(target, content)
    return _ok(path=path, action=action)


def memory_list() -> str:
    """List INDEX.md entries (path + description) for initial filtering."""
    try:
        index = _resolve_path(INDEX_FILE)
    except ToolError as exc:
        return _err(str(exc))
    if not index.is_file():
        return _ok(entries=[])
    entries = _parse_index(index.read_text(encoding="utf-8"))
    return _ok(entries=entries)


def index_update(entries: list[dict[str, Any]]) -> str:
    """Regenerate INDEX.md from the given entries (full-file replacement).

    Called by the index agent. ``entries`` is a list of
    ``{"path", "description", "related"}`` dicts; the file is written
    atomically in the canonical INDEX.md format.
    """
    try:
        validated = [IndexEntry.model_validate(e) for e in entries]
    except Exception as exc:
        return _err(f"invalid entries: {exc}")
    try:
        target = _resolve_path(INDEX_FILE)
    except ToolError as exc:
        return _err(str(exc))
    _atomic_write(target, _render_index(validated))
    return _ok(count=len(validated))


def spawn_reader(path: str, *, client: LLMClient | None = None) -> str:
    """Spawn a reader agent for a single memory document.

    Returns ``ReaderAgentOutput`` JSON (summary + key_topics +
    category_hint). Used by the index agent to keep its own context
    small while summarizing every document.
    """
    try:
        target = _resolve_path(path)
    except ToolError as exc:
        return _err(str(exc))
    if not target.is_file():
        return _err(f"file not found: {path}")
    content = target.read_text(encoding="utf-8")

    # Lazy import to avoid a module-level cycle (agent_loop imports tools).
    from tabularius.agent_loop import run_agent

    output = run_agent(
        READER_SYSTEM_PROMPT,
        f"Path: {path}\n\n{content}",
        [],
        ReaderAgentOutput,
        client=client,
    )
    return output.model_dump_json()


# ── INDEX.md helpers ─────────────────────────────────────────────────────────


def _parse_index(content: str) -> list[dict[str, str]]:
    """Parse the ``## Categories`` section into [{path, description}]."""
    entries: list[dict[str, str]] = []
    in_categories = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "## Categories":
            in_categories = True
            continue
        if in_categories and stripped.startswith("## "):
            break
        if in_categories and stripped.startswith("- `"):
            rest = stripped[3:]
            path, sep, description = rest.partition("`")
            if sep:
                description = description.lstrip("-—–: ").strip()
                entries.append({"path": path.strip(), "description": description})
    return entries


def _render_index(entries: list[IndexEntry]) -> str:
    lines = [
        "# Memory Index",
        "",
        "<!-- auto-generated by tabularius; edit via reindex -->",
        "",
        "## Categories",
    ]
    for entry in entries:
        lines.append(f"- `{entry.path}` — {entry.description}")
    return "\n".join(lines) + "\n"


# ── OpenAI function-calling surface ──────────────────────────────────────────


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "memory_read",
            "description": (
                "Read a single .md file from the memory directory. "
                "Returns the file content, or an error if the file does not exist."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative .md path, e.g. uniterra-vps-infra.md",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_write",
            "description": (
                "Write a memory document atomically. action='create' requires the "
                "file to NOT exist; action='merge' requires it to exist — read the "
                "current file first, then pass the FINAL complete merged content. "
                "Never passes partial content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative .md path"},
                    "content": {"type": "string", "description": "Final complete file content"},
                    "action": {"type": "string", "enum": ["create", "merge"]},
                },
                "required": ["path", "content", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_list",
            "description": (
                "List all INDEX.md entries (path + description). "
                "Use for initial filtering before deciding which documents to read."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "index_update",
            "description": (
                "Regenerate INDEX.md from the given entries "
                "(path + description). Replaces the whole file atomically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entries": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "description": {"type": "string"},
                                "related": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["path", "description"],
                        },
                    }
                },
                "required": ["entries"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_reader",
            "description": (
                "Spawn a reader agent for a memory document path. "
                "Returns its summary, key topics, and category hint "
                "(ReaderAgentOutput)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative .md path"}},
                "required": ["path"],
            },
        },
    },
]

# name -> callable, used by the agent loop's default dispatch.
TOOL_REGISTRY: dict[str, Callable[..., str]] = {
    "memory_read": memory_read,
    "memory_write": memory_write,
    "memory_list": memory_list,
    "index_update": index_update,
    "spawn_reader": spawn_reader,
}
