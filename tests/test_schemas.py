"""Tests for schemas.py — Pydantic output contracts + parse_or_retry."""

import pytest
from pydantic import ValidationError

from tabularius.schemas import (
    IndexAgentOutput,
    IndexEntry,
    MemoryAgentOutput,
    MemoryDocument,
    ReaderAgentOutput,
    RecallAgentOutput,
    SchemaParseError,
    parse_or_retry,
)


class TestMemoryDocument:
    def test_valid_create(self) -> None:
        doc = MemoryDocument.model_validate(
            {
                "action": "create",
                "path": "new-topic.md",
                "content": "# New Topic\n",
                "reason": "new category",
            }
        )
        assert doc.action == "create"
        assert doc.path == "new-topic.md"

    def test_valid_merge(self) -> None:
        doc = MemoryDocument.model_validate(
            {
                "action": "merge",
                "path": "existing.md",
                "content": "# Existing\nmore\n",
                "reason": "update",
            }
        )
        assert doc.action == "merge"

    def test_invalid_action_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MemoryDocument.model_validate(
                {
                    "action": "overwrite",
                    "path": "x.md",
                    "content": "x",
                    "reason": "r",
                }
            )

    def test_missing_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MemoryDocument.model_validate({"action": "create", "path": "x.md"})


class TestMemoryAgentOutput:
    def test_roundtrip(self) -> None:
        data = {
            "documents": [
                {
                    "action": "merge",
                    "path": "a.md",
                    "content": "A",
                    "reason": "r1",
                }
            ],
            "processed_sessions": ["s1", "s2"],
            "stats": {"docs": 1, "sessions": 2},
        }
        out = MemoryAgentOutput.model_validate(data)
        assert len(out.documents) == 1
        assert out.processed_sessions == ["s1", "s2"]
        assert out.stats["docs"] == 1

    def test_empty_documents_ok(self) -> None:
        out = MemoryAgentOutput.model_validate(
            {"documents": [], "processed_sessions": [], "stats": {}}
        )
        assert out.documents == []


class TestRecallAgentOutput:
    def test_roundtrip(self) -> None:
        out = RecallAgentOutput.model_validate(
            {
                "context_block": "## 記憶上下文\n...",
                "documents_used": ["a.md"],
                "relevance_notes": "high",
            }
        )
        assert "記憶上下文" in out.context_block
        assert out.documents_used == ["a.md"]


class TestReaderAgentOutput:
    def test_roundtrip(self) -> None:
        out = ReaderAgentOutput.model_validate(
            {
                "path": "a.md",
                "summary": "Summary here",
                "key_topics": ["t1", "t2"],
                "category_hint": "topic-a",
            }
        )
        assert out.key_topics == ["t1", "t2"]


class TestIndexEntry:
    def test_roundtrip(self) -> None:
        e = IndexEntry.model_validate({"path": "a.md", "description": "Desc", "related": ["b.md"]})
        assert e.related == ["b.md"]

    def test_related_optional(self) -> None:
        e = IndexEntry.model_validate({"path": "a.md", "description": "Desc"})
        assert e.related == []


class TestIndexAgentOutput:
    def test_roundtrip(self) -> None:
        out = IndexAgentOutput.model_validate(
            {
                "index_entries": [{"path": "a.md", "description": "Desc", "related": []}],
                "stats": {"count": 1},
            }
        )
        assert len(out.index_entries) == 1


class TestParseOrRetry:
    def test_valid_json_parses(self) -> None:
        out = parse_or_retry(
            '{"path": "a.md", "summary": "s", "key_topics": [], "category_hint": "c"}',
            ReaderAgentOutput,
        )
        assert isinstance(out, ReaderAgentOutput)

    def test_invalid_json_raises_schema_parse_error(self) -> None:
        with pytest.raises(SchemaParseError):
            parse_or_retry("not json at all {{{", ReaderAgentOutput)

    def test_json_repair_fallback_recovers(self) -> None:
        # Broken JSON: unquoted keys + trailing comma — json_repair fixes it.
        content = '{path: "a.md", summary: "s", key_topics: ["x",], category_hint: "c",}'
        out = parse_or_retry(content, ReaderAgentOutput)
        assert isinstance(out, ReaderAgentOutput)
        assert out.path == "a.md"

    def test_repaired_but_wrong_shape_still_raises(self) -> None:
        # json_repair produces a dict, but it fails schema validation.
        content = '{path: "a.md"}'  # missing required fields
        with pytest.raises(SchemaParseError):
            parse_or_retry(content, ReaderAgentOutput)
