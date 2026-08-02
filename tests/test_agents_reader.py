"""Tests for agents/reader.py — reader agent (issue #9)."""

from __future__ import annotations

import pytest
from fakes import _FakeMessage, _FakeResponse, _ScriptedClient, reader_output_json

from tabularius.agents import reader
from tabularius.schemas import ReaderAgentOutput
from tabularius.tools import ToolError


class TestRunReader:
    def test_reads_document_and_returns_output(self, memory_root) -> None:
        (memory_root / "a.md").write_text("# A\ncontent", encoding="utf-8")
        client = _ScriptedClient([_FakeResponse(_FakeMessage(reader_output_json()))])
        out = reader.run_reader("a.md", client=client)  # type: ignore[arg-type]
        assert isinstance(out, ReaderAgentOutput)
        assert out.path == "a.md"
        user = client.messages_seen[0][1]["content"]
        assert "a.md" in user
        assert "content" in user

    def test_missing_file_raises_tool_error(self, memory_root) -> None:
        with pytest.raises(ToolError):
            reader.run_reader("missing.md")

    def test_traversal_raises_tool_error(self, memory_root) -> None:
        with pytest.raises(ToolError):
            reader.run_reader("../evil.md")
