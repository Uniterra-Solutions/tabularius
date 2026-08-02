"""Tests for agent_loop.py — generic tool-calling loop."""

import json
from types import SimpleNamespace

import pytest

from tabularius import agent_loop
from tabularius.schemas import ReaderAgentOutput, SchemaParseError


class _FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=True):
        data = {"role": "assistant"}
        if self.content is not None:
            data["content"] = self.content
        if self.tool_calls:
            data["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {
                        "name": c.function.name,
                        "arguments": c.function.arguments,
                    },
                }
                for c in self.tool_calls
            ]
        return data


class _FakeResponse:
    def __init__(self, message: _FakeMessage):
        self.choices = [SimpleNamespace(message=message)]


class _ScriptedClient:
    """LLMClient duck-type that returns scripted responses and records messages."""

    def __init__(self, responses: list[_FakeResponse]):
        self.responses = list(responses)
        self.messages_seen: list[list[dict]] = []

    def chat(self, messages, tools=None, timeout=None):
        self.messages_seen.append(list(messages))
        return self.responses.pop(0)


def _tool_call(name: str, arguments: dict, call_id: str = "call_1"):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _valid_reader_json() -> str:
    return json.dumps(
        {
            "path": "a.md",
            "summary": "s",
            "key_topics": ["t"],
            "category_hint": "c",
        }
    )


def _two_round_responses():
    return [
        _FakeResponse(_FakeMessage(tool_calls=[_tool_call("memory_read", {"path": "a.md"})])),
        _FakeResponse(_FakeMessage(_valid_reader_json())),
    ]


class TestRunAgent:
    def test_no_tool_direct_json(self) -> None:
        client = _ScriptedClient([_FakeResponse(_FakeMessage(_valid_reader_json()))])
        out = agent_loop.run_agent(
            "system",
            "user",
            [],
            ReaderAgentOutput,
            client=client,  # type: ignore[arg-type]
        )
        assert isinstance(out, ReaderAgentOutput)
        assert out.path == "a.md"
        # Only the initial two messages were sent — no corrective round.
        assert len(client.messages_seen) == 1

    def test_two_round_tool_call_flow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[str, dict]] = []

        def fake_dispatch(name: str, args: dict) -> str:
            calls.append((name, args))
            return json.dumps({"ok": True, "content": "file content"})

        client = _ScriptedClient(_two_round_responses())
        out = agent_loop.run_agent(
            "system",
            "user",
            [{"type": "function", "function": {"name": "memory_read"}}],
            ReaderAgentOutput,
            client=client,  # type: ignore[arg-type]
            dispatch=fake_dispatch,
        )
        assert isinstance(out, ReaderAgentOutput)
        assert calls == [("memory_read", {"path": "a.md"})]
        # Round 1: system+user; round 2: system+user+assistant tool_call+tool result.
        assert len(client.messages_seen) == 2
        second_round = client.messages_seen[1]
        roles = [m["role"] for m in second_round]
        assert roles == ["system", "user", "assistant", "tool"]
        assert second_round[2]["tool_calls"][0]["function"]["name"] == "memory_read"
        assert second_round[3]["tool_call_id"] == "call_1"

    def test_default_dispatch_uses_registry(self, memory_root) -> None:
        (memory_root / "a.md").write_text("hello", encoding="utf-8")
        client = _ScriptedClient(_two_round_responses())
        out = agent_loop.run_agent(
            "system",
            "user",
            [{"type": "function", "function": {"name": "memory_read"}}],
            ReaderAgentOutput,
            client=client,  # type: ignore[arg-type]
        )
        assert isinstance(out, ReaderAgentOutput)
        tool_result = client.messages_seen[1][3]["content"]
        assert json.loads(tool_result)["content"] == "hello"

    def test_schema_violation_retries_with_feedback(self) -> None:
        client = _ScriptedClient(
            [
                _FakeResponse(_FakeMessage("not valid json")),
                _FakeResponse(_FakeMessage(_valid_reader_json())),
            ]
        )
        out = agent_loop.run_agent(
            "system",
            "user",
            [],
            ReaderAgentOutput,
            client=client,  # type: ignore[arg-type]
        )
        assert isinstance(out, ReaderAgentOutput)
        assert len(client.messages_seen) == 2
        corrective = client.messages_seen[1][2]
        assert corrective["role"] == "user"
        assert "schema" in corrective["content"]

    def test_schema_violation_exhausts_retries(self) -> None:
        client = _ScriptedClient([_FakeResponse(_FakeMessage("bad"))] * 3)
        with pytest.raises(SchemaParseError):
            agent_loop.run_agent(
                "system",
                "user",
                [],
                ReaderAgentOutput,
                client=client,  # type: ignore[arg-type]
            )
        assert len(client.messages_seen) == agent_loop.MAX_SCHEMA_RETRIES + 1

    def test_unknown_tool_returns_error_json_and_continues(self) -> None:
        client = _ScriptedClient(
            [
                _FakeResponse(_FakeMessage(tool_calls=[_tool_call("nope", {})])),
                _FakeResponse(_FakeMessage(_valid_reader_json())),
            ]
        )
        out = agent_loop.run_agent(
            "system",
            "user",
            [],
            ReaderAgentOutput,
            client=client,  # type: ignore[arg-type]
        )
        assert isinstance(out, ReaderAgentOutput)
        assert "unknown tool" in client.messages_seen[1][3]["content"]

    def test_raising_tool_feeds_error_back(self) -> None:
        def boom(name: str, args: dict) -> str:
            raise OSError("disk full")

        client = _ScriptedClient(
            [
                _FakeResponse(
                    _FakeMessage(tool_calls=[_tool_call("memory_read", {"path": "a.md"})])
                ),
                _FakeResponse(_FakeMessage(_valid_reader_json())),
            ]
        )
        out = agent_loop.run_agent(
            "system",
            "user",
            [],
            ReaderAgentOutput,
            client=client,  # type: ignore[arg-type]
            dispatch=boom,
        )
        assert isinstance(out, ReaderAgentOutput)
        tool_result = json.loads(client.messages_seen[1][3]["content"])
        assert tool_result["ok"] is False
        assert "disk full" in tool_result["error"]

    def test_empty_choices_raises_clear_error(self) -> None:
        # Some relays return HTTP 200 with choices=[] on failure; the loop must
        # raise a clear RuntimeError, not a bare IndexError.
        class _NoChoices:
            choices: list = []

        client = _ScriptedClient([_NoChoices()])  # type: ignore[list-item]
        with pytest.raises(RuntimeError, match="no choices"):
            agent_loop.run_agent(
                "system",
                "user",
                [],
                ReaderAgentOutput,
                client=client,  # type: ignore[arg-type]
            )

    def test_tool_round_limit_raises(self) -> None:
        responses = [
            _FakeResponse(_FakeMessage(tool_calls=[_tool_call("memory_read", {"path": "a.md"})]))
        ] * (agent_loop.MAX_TOOL_ROUNDS + 1)
        client = _ScriptedClient(responses)
        with pytest.raises(RuntimeError, match="tool rounds"):
            agent_loop.run_agent(
                "system",
                "user",
                [],
                ReaderAgentOutput,
                client=client,  # type: ignore[arg-type]
            )
