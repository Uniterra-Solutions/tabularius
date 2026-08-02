"""Reader agent — one memory document -> summary + topics (issue #9).

The reader produces ``ReaderAgentOutput`` (summary, key_topics,
category_hint) for a single document. ``tools.spawn_reader`` delegates
here, and the index agent calls :func:`run_reader` for every document so
its own context stays small.
"""

from __future__ import annotations

from tabularius.llm import LLMClient
from tabularius.prompts import load_prompt
from tabularius.schemas import ReaderAgentOutput
from tabularius.tools import _read_document


def run_reader(path: str, *, client: LLMClient | None = None) -> ReaderAgentOutput:
    """Summarize the memory document at ``path``.

    Reads the document through the ``memory_read`` tool (path safety and
    missing-file errors become :class:`ToolError`), then runs the reader
    prompt and returns a validated ``ReaderAgentOutput``.
    """
    content = _read_document(path)
    # Resolved at call time so tests can stub the loop
    # (``tabularius.agent_loop.run_agent``) without import-order coupling.
    from tabularius.agent_loop import run_agent

    return run_agent(
        load_prompt("reader"),
        f"Path: {path}\n\n{content}",
        [],
        ReaderAgentOutput,
        client=client,
    )
