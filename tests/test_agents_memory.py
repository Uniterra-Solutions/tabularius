"""Tests for agents/memory.py — memory agent (issue #7)."""

from __future__ import annotations

from fakes import _FakeMessage, _FakeResponse, _ScriptedClient, memory_output_json, tool_call

from tabularius.agents import memory
from tabularius.prompts import PROMPTS_DIR, load_prompt
from tabularius.schemas import MemoryAgentOutput


def _five_transcripts() -> list[str]:
    return [f"transcript {index}" for index in range(1, 6)]


class TestRunMemoryAgent:
    def test_batch_transcripts_produce_output(self, memory_root) -> None:
        client = _ScriptedClient([_FakeResponse(_FakeMessage(memory_output_json()))])
        out = memory.run_memory_agent(_five_transcripts(), client=client)  # type: ignore[arg-type]
        assert isinstance(out, MemoryAgentOutput)
        assert out.documents[0].action == "merge"

        user = client.messages_seen[0][1]["content"]
        assert "Session 1" in user
        assert "transcript 5" in user
        # Only read-only tools are exposed to the model — the system writes.
        names = [schema["function"]["name"] for schema in client.tools_seen[0] or []]
        assert set(names) == {"memory_read", "memory_list"}

    def test_agent_reads_existing_then_emits_merge(self, memory_root) -> None:
        """The agent must read existing content and return it in a merge doc.

        Writes are performed by the system (CLI/provider), never by the
        agent loop — so a read followed by a merge-typed document proves
        the agent preserved the old content for the system to apply.
        """
        (memory_root / "uniterra-vps-infra.md").write_text("# VPS\nold info\n", encoding="utf-8")
        responses = [
            _FakeResponse(
                _FakeMessage(
                    tool_calls=[tool_call("memory_read", {"path": "uniterra-vps-infra.md"})]
                )
            ),
            _FakeResponse(
                _FakeMessage(
                    memory_output_json(
                        path="uniterra-vps-infra.md",
                        content="# VPS\nold info\nnew info\n",
                    )
                )
            ),
        ]
        client = _ScriptedClient(responses)
        out = memory.run_memory_agent(["a transcript"], client=client)  # type: ignore[arg-type]
        # The system applies this document; the agent must have included the
        # old content in the final merged content.
        doc = out.documents[0]
        assert doc.action == "merge"
        assert doc.path == "uniterra-vps-infra.md"
        assert "old info" in doc.content
        assert "new info" in doc.content


class TestPrompts:
    def test_extraction_prompt_versioned_in_prompts_dir(self) -> None:
        assert (PROMPTS_DIR / "memory.md").is_file()
        prompt = load_prompt("memory")
        assert "v2" in prompt
        assert "memory_read" in prompt
        assert "memory_list" in prompt
        assert "merge" in prompt
