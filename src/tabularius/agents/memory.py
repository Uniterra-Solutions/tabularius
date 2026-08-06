"""Memory agent — session transcripts -> topic-classified .md documents (issue #7).

Given a batch of session transcripts (typically 5, passed by the Hermes
integration's ``on_session_end``), the agent classifies information into
existing topic files — reading the current content first and merging,
never overwriting — and creates a new file only when no existing file
covers the topic. Output is ``MemoryAgentOutput``.
"""

from __future__ import annotations

from typing import Any

from tabularius.agent_loop import DispatchFn, run_agent
from tabularius.llm import LLMClient
from tabularius.prompts import load_prompt
from tabularius.schemas import MemoryAgentOutput
from tabularius.tools import TOOL_SCHEMAS

MEMORY_TOOL_NAMES = ("memory_read", "memory_list")
MEMORY_TOOLS: list[dict[str, Any]] = [
    schema for schema in TOOL_SCHEMAS if schema["function"]["name"] in MEMORY_TOOL_NAMES
]


def run_memory_agent(
    transcripts: list[str],
    *,
    client: LLMClient | None = None,
    dispatch: DispatchFn | None = None,
) -> MemoryAgentOutput:
    """Extract durable information from a batch of session transcripts."""
    return run_agent(
        load_prompt("memory"),
        _format_transcripts(transcripts),
        MEMORY_TOOLS,
        MemoryAgentOutput,
        client=client,
        dispatch=dispatch,
    )


def _format_transcripts(transcripts: list[str]) -> str:
    """Render a transcript batch as numbered sessions for the LLM."""
    if not transcripts:
        return "No transcripts were provided."
    parts = [f"Process the following {len(transcripts)} session transcripts in one batch.", ""]
    for index, transcript in enumerate(transcripts, start=1):
        parts.append(f"## Session {index}")
        parts.append(transcript)
    return "\n".join(parts)
