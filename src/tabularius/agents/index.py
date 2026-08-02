"""Index agent — regenerate INDEX.md and every document's Related (issue #9).

Flow:
1. list every memory document
2. spawn a reader per document (keeps the index agent's own context small)
3. let the LLM classify + judge relatedness from the summaries (zero vectors)
4. write INDEX.md and append a ``## Related`` block (3-5 entries) at the
   bottom of every document

Reindexing is deterministic given the same reader/classification outputs:
the document scan is sorted, INDEX.md renders in that order, and the
Related block is strip-and-appended atomically.
"""

from __future__ import annotations

import json

from tabularius.agent_loop import run_agent
from tabularius.agents.reader import run_reader
from tabularius.llm import LLMClient
from tabularius.prompts import load_prompt
from tabularius.schemas import IndexAgentOutput, IndexEntry, ReaderAgentOutput
from tabularius.tools import (
    INDEX_FILE,
    ToolError,
    _read_document,
    index_update,
    memory_dir,
    memory_write,
)

MAX_RELATED = 5


def run_index_agent(
    *,
    client: LLMClient | None = None,
    reader_client: LLMClient | None = None,
) -> IndexAgentOutput:
    """Regenerate INDEX.md and every document's ``## Related`` block."""
    paths = _list_memory_documents()
    readers = [run_reader(path, client=reader_client) for path in paths]

    output = run_agent(
        load_prompt("index"),
        _format_index_user(readers),
        [],
        IndexAgentOutput,
        client=client,
    )

    entries = _build_entries(output.index_entries, paths, readers)

    index_update([entry.model_dump() for entry in entries])
    for entry in entries:
        if entry.related:
            _write_related_block(entry.path, entry.related)

    return IndexAgentOutput(
        index_entries=entries,
        stats={"documents": len(paths), "entries": len(entries)},
    )


def _list_memory_documents() -> list[str]:
    """Top-level .md files in the memory dir, sorted, excluding INDEX.md."""
    root = memory_dir()
    return sorted(path.name for path in root.glob("*.md") if path.name != INDEX_FILE)


def _build_entries(
    llm_entries: list[IndexEntry],
    paths: list[str],
    readers: list[ReaderAgentOutput],
) -> list[IndexEntry]:
    """Normalize LLM entries: drop hallucinated paths, cap related, fill gaps.

    Every scanned document must appear in INDEX.md; documents the LLM
    missed get an entry derived from their reader summary.
    """
    readers_by_path = {reader.path: reader for reader in readers}
    by_path = {entry.path: entry for entry in llm_entries}
    entries: list[IndexEntry] = []
    for path in paths:
        entry = by_path.get(path)
        if entry is None:
            entries.append(
                IndexEntry(path=path, description=readers_by_path[path].summary, related=[])
            )
            continue
        related = [rel for rel in entry.related if rel in paths and rel != path]
        entries.append(
            IndexEntry(path=path, description=entry.description, related=related[:MAX_RELATED])
        )
    return entries


def _format_index_user(readers: list[ReaderAgentOutput]) -> str:
    parts = [
        "Index the following memory documents. For each document output an "
        "IndexEntry with path, a concise description, and related "
        f"(3-{MAX_RELATED} most related document paths).",
        "",
    ]
    for reader in readers:
        parts.append(f"## {reader.path}")
        parts.append(f"summary: {reader.summary}")
        parts.append(f"topics: {', '.join(reader.key_topics)}")
        parts.append(f"category_hint: {reader.category_hint}")
    return "\n".join(parts)


def _strip_related(content: str) -> str:
    """Remove the trailing ``## Related`` section (always appended last)."""
    marker = "## Related"
    index = content.find(marker)
    if index == -1:
        return content
    return content[:index].rstrip() + "\n"


def _write_related_block(path: str, related: list[str]) -> None:
    """Append/replace the ``## Related`` block of one document (atomic)."""
    content = _strip_related(_read_document(path))
    block = f"{content.rstrip()}\n\n## Related\n" + "".join(f"- {rel}\n" for rel in related)
    write_result = json.loads(memory_write(path, block, "merge"))
    if not write_result.get("ok"):
        raise ToolError(str(write_result.get("error") or f"write failed: {path}"))


__all__ = ["run_index_agent"]
