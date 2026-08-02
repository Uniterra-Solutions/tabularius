"""Tests for agents/recall.py — recall agent (issue #8)."""

from __future__ import annotations

import httpx
import pytest
from fakes import _FakeMessage, _FakeResponse, _ScriptedClient, recall_output_json
from openai import APITimeoutError

from tabularius.agents import recall
from tabularius.schemas import RecallAgentOutput


@pytest.fixture
def index_with_docs(memory_root) -> None:
    (memory_root / "a.md").write_text("# A\ncontent a", encoding="utf-8")
    (memory_root / "b.md").write_text("# B\ncontent b", encoding="utf-8")
    (memory_root / "INDEX.md").write_text(
        "# Memory Index\n\n## Categories\n- `a.md` — Doc A\n- `b.md` — Doc B\n",
        encoding="utf-8",
    )


def _timeout_error() -> APITimeoutError:
    req = httpx.Request("POST", "https://api.uniterra-solutions.com/v1/chat/completions")
    return APITimeoutError(request=req)


class TestRunRecallAgent:
    def test_first_call_preloads_most_used_docs(self, memory_root, index_with_docs) -> None:
        session = recall.RecallSession(preload_paths=["a.md"])
        client = _ScriptedClient([_FakeResponse(_FakeMessage(recall_output_json()))])
        out = recall.run_recall_agent("vps setup", session=session, client=client)  # type: ignore[arg-type]
        assert isinstance(out, RecallAgentOutput)
        user = client.messages_seen[0][1]["content"]
        assert "content a" in user  # preloaded content is in context
        assert "a.md" in session.prefetched
        # Only memory_read is exposed to the model.
        names = [schema["function"]["name"] for schema in client.tools_seen[0] or []]
        assert names == ["memory_read"]

    def test_second_call_does_not_reread(self, memory_root, index_with_docs) -> None:
        session = recall.RecallSession(preload_paths=["a.md"])
        responses = [_FakeResponse(_FakeMessage(recall_output_json()))] * 2
        client = _ScriptedClient(responses)
        recall.run_recall_agent("q1", session=session, client=client)  # type: ignore[arg-type]
        recall.run_recall_agent("q2", session=session, client=client)  # type: ignore[arg-type]

        first_user = client.messages_seen[0][1]["content"]
        second_user = client.messages_seen[1][1]["content"]
        assert "content a" in first_user
        # Second call must not re-include the content and must mark it loaded.
        assert "content a" not in second_user
        assert "a.md" in second_user
        assert "do not re-read" in second_user

    def test_timeout_returns_empty_context(self, memory_root, index_with_docs) -> None:
        class _TimeoutClient:
            def chat(self, messages, tools=None, timeout=None):
                raise _timeout_error()

        out = recall.run_recall_agent(
            "q",
            client=_TimeoutClient(),  # type: ignore[arg-type]
            timeout=recall.RECALL_TIMEOUT,
        )
        assert out.context_block == ""
        assert out.documents_used == []
        assert out.relevance_notes == ""

    def test_no_index_returns_model_output(self, memory_root) -> None:
        client = _ScriptedClient(
            [_FakeResponse(_FakeMessage(recall_output_json(context_block="")))]
        )
        out = recall.run_recall_agent("q", client=client)  # type: ignore[arg-type]
        assert out.context_block == ""
