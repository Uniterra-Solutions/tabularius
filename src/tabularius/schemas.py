"""Pydantic output contracts for all tabularius agents.

Every agent returns JSON; these models define the contract, and
``model_validate_json`` performs parse + validation. ``parse_or_retry``
adds a ``json_repair`` fallback for LLM output that is close to valid.
"""

from __future__ import annotations

from typing import Any, Literal

import json_repair
from pydantic import BaseModel, ValidationError


class MemoryDocument(BaseModel):
    """One document to merge into or create in the memory directory."""

    action: Literal["merge", "create"]
    path: str
    content: str
    reason: str


class MemoryAgentOutput(BaseModel):
    """Output of the memory agent (extract session transcripts -> .md files)."""

    documents: list[MemoryDocument]
    processed_sessions: list[str]
    stats: dict[str, Any]


class RecallAgentOutput(BaseModel):
    """Output of the recall agent (query -> context block for injection)."""

    context_block: str
    documents_used: list[str]
    relevance_notes: str


class ReaderAgentOutput(BaseModel):
    """Output of the reader agent (single document -> summary + topics)."""

    path: str
    summary: str
    key_topics: list[str]
    category_hint: str


class IndexEntry(BaseModel):
    """One entry in INDEX.md (path + description + related documents)."""

    path: str
    description: str
    related: list[str] = []


class IndexAgentOutput(BaseModel):
    """Output of the index agent (full INDEX.md regeneration)."""

    index_entries: list[IndexEntry]
    stats: dict[str, Any]


class SchemaParseError(ValueError):
    """Raised when content cannot be parsed/validated into the target schema."""


def parse_or_retry(content: str, schema: type[BaseModel]) -> BaseModel:
    """Parse ``content`` into ``schema``, falling back to json_repair.

    Raises ``SchemaParseError`` (a ValueError) when neither pydantic's
    ``model_validate_json`` nor ``json_repair`` can produce a valid
    instance. Callers (e.g. the agent loop) use this to detect schema
    violations and retry with corrective feedback.
    """
    try:
        return schema.model_validate_json(content)
    except ValidationError:
        try:
            repaired = json_repair.loads(content)
        except Exception as repair_error:  # json_repair raises on unfixable input
            raise SchemaParseError(
                f"json_repair failed for schema {schema.__name__}: {repair_error}"
            ) from repair_error
        try:
            return schema.model_validate(repaired)
        except ValidationError as validate_error:
            raise SchemaParseError(
                f"repaired JSON still invalid for schema {schema.__name__}: {validate_error}"
            ) from validate_error
