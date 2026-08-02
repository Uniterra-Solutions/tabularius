"""Recall agent — query -> relevant memory context for prompt injection (issue #8).

The recall agent reads INDEX.md (small), lets the LLM pick up to 3
candidate documents, reads them, and returns a concise context block
(``## 記憶上下文``). Cost control is per-session:

- first call: INDEX.md entries + the 2-3 most-used documents (preloaded)
- later calls: INDEX.md filter only; documents already loaded this session
  are listed and never re-read (``RecallSession`` cache)
- short timeout: on ``APITimeoutError`` return an empty context instead of
  blocking the conversation
"""

from __future__ import annotations

import json
from typing import Any

from openai import APITimeoutError

from tabularius.agent_loop import DispatchFn, _default_dispatch, run_agent
from tabularius.llm import LLMClient
from tabularius.prompts import load_prompt
from tabularius.schemas import RecallAgentOutput
from tabularius.tools import TOOL_SCHEMAS, memory_list, memory_read

RECALL_TIMEOUT = 5.0
PRELOAD_COUNT = 3
MAX_CANDIDATES = 3
RECALL_TOOLS: list[dict[str, Any]] = [
    schema for schema in TOOL_SCHEMAS if schema["function"]["name"] == "memory_read"
]


class RecallSession:
    """Per-session cache of documents the recall agent has already loaded.

    ``preload_paths`` are the "most-used" documents loaded on the first
    call of the session (the integration layer decides which; the first
    INDEX.md entries are the fallback). Every document read through
    ``memory_read`` is recorded so later calls do not re-read it.
    """

    def __init__(self, preload_paths: list[str] | None = None) -> None:
        self._preload_paths: list[str] = list(preload_paths or [])
        self._prefetched: set[str] = set()
        self._initialized = False

    @property
    def preload_paths(self) -> list[str]:
        return list(self._preload_paths)

    @property
    def prefetched(self) -> set[str]:
        return set(self._prefetched)

    @property
    def initialized(self) -> bool:
        return self._initialized

    def mark_initialized(self) -> None:
        self._initialized = True

    def mark_read(self, path: str) -> None:
        self._prefetched.add(path)

    def reset(self) -> None:
        """Forget everything loaded (used to retry a failed first call)."""
        self._prefetched.clear()
        self._initialized = False


def run_recall_agent(
    query: str,
    *,
    session: RecallSession | None = None,
    client: LLMClient | None = None,
    dispatch: DispatchFn | None = None,
    timeout: float = RECALL_TIMEOUT,
) -> RecallAgentOutput:
    """Retrieve relevant memory context for ``query``.

    On timeout the call returns an empty ``context_block`` instead of
    raising, so a slow or unavailable LLM never blocks the conversation.
    """
    session = session or RecallSession()
    entries = _index_entries()
    was_initialized = session.initialized

    preloaded: list[tuple[str, str]] = []
    if not session.initialized:
        session.mark_initialized()
        candidates = session.preload_paths or [entry["path"] for entry in entries[:PRELOAD_COUNT]]
        for path in candidates:
            result = json.loads(memory_read(path))
            if result.get("ok"):
                preloaded.append((path, result["content"]))
                session.mark_read(path)

    user = _format_recall_user(query, entries, session.prefetched, preloaded)

    def _tracking_dispatch(name: str, args: dict[str, Any]) -> str:
        result = (dispatch or _default_dispatch)(name, args)
        if name == "memory_read":
            payload = json.loads(result)
            if payload.get("ok"):
                session.mark_read(args.get("path", ""))
        return result

    try:
        return run_agent(
            load_prompt("recall"),
            user,
            RECALL_TOOLS,
            RecallAgentOutput,
            client=client,
            dispatch=_tracking_dispatch,
            timeout=timeout,
        )
    except APITimeoutError:
        # A timed-out FIRST call never delivered its preloaded content; reset
        # the session so the next call re-preloads instead of skipping it.
        if not was_initialized:
            session.reset()
        return RecallAgentOutput(context_block="", documents_used=[], relevance_notes="")


def _index_entries() -> list[dict[str, str]]:
    """INDEX.md entries via the memory_list tool: [{path, description}]."""
    result = json.loads(memory_list())
    entries: list[dict[str, str]] = result.get("entries", [])
    return entries


def _format_recall_user(
    query: str,
    entries: list[dict[str, str]],
    prefetched: set[str],
    preloaded: list[tuple[str, str]],
) -> str:
    lines = [f"Query: {query}", "", "## Memory Index"]
    if entries:
        lines.extend(f"- `{entry['path']}` — {entry['description']}" for entry in entries)
    else:
        lines.append("(no memory documents indexed)")
    lines.append("")
    if preloaded:
        lines.append("## Preloaded this session")
        for path, content in preloaded:
            lines.append(f"### {path}")
            lines.append(content)
    else:
        lines.append("## Already loaded this session (do not re-read)")
        for path in sorted(prefetched):
            lines.append(f"- {path}")
        if not prefetched:
            lines.append("(none)")
    lines.append("")
    lines.append(
        f"Select up to {MAX_CANDIDATES} relevant documents from the index that are "
        "NOT already loaded, read each with memory_read, then return the "
        "RecallAgentOutput JSON."
    )
    return "\n".join(lines)
