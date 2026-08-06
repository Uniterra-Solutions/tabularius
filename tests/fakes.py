"""Shared scripted-LLM fakes for agent tests (no network).

Tests live in the same directory without an ``__init__.py``, so pytest
inserts ``tests/`` on ``sys.path`` and ``from fakes import ...`` works.
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from typing import Any


def make_state_db(path, session_rows, message_rows) -> None:
    """Create a Hermes-shaped state.db fixture (sessions + messages)."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at REAL, message_count INTEGER)"
    )
    conn.execute(
        "CREATE TABLE messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT,"
        " content TEXT, timestamp REAL)"
    )
    for row in session_rows:
        conn.execute("INSERT INTO sessions (id, started_at, message_count) VALUES (?,?,?)", row)
    for row in message_rows:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?,?,?,?)", row
        )
    conn.commit()
    conn.close()


class _FakeMessage:
    def __init__(self, content: str | None = None, tool_calls: list[Any] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {"role": "assistant"}
        if self.content is not None:
            data["content"] = self.content
        if self.tool_calls:
            data["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]
        return data


class _FakeResponse:
    def __init__(self, message: _FakeMessage) -> None:
        self.choices = [SimpleNamespace(message=message)]


class _ScriptedClient:
    """LLMClient duck-type returning scripted responses and recording calls."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.messages_seen: list[list[dict[str, Any]]] = []
        self.tools_seen: list[list[dict[str, Any]] | None] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> _FakeResponse:
        self.messages_seen.append(list(messages))
        self.tools_seen.append(tools)
        return self.responses.pop(0)


def tool_call(name: str, arguments: dict[str, Any], call_id: str = "call_1") -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def memory_output_json(path: str = "a.md", content: str = "# A\n", action: str = "merge") -> str:
    return json.dumps(
        {
            "documents": [{"action": action, "path": path, "content": content, "reason": "r"}],
            "processed_sessions": ["s1"],
            "stats": {"docs": 1, "sessions": 1},
        }
    )


def recall_output_json(context_block: str = "## 記憶上下文\nrelevant facts") -> str:
    return json.dumps(
        {
            "context_block": context_block,
            "documents_used": ["a.md"],
            "relevance_notes": "matches query",
        }
    )


def reader_output_json() -> str:
    return json.dumps(
        {
            "path": "a.md",
            "summary": "summary",
            "key_topics": ["t"],
            "category_hint": "c",
        }
    )


def index_output_json() -> str:
    return json.dumps(
        {
            "index_entries": [
                {"path": "a.md", "description": "A desc", "related": ["b.md", "c.md"]},
                {"path": "b.md", "description": "B desc", "related": ["a.md", "c.md"]},
                {"path": "c.md", "description": "C desc", "related": ["a.md", "b.md"]},
            ],
            "stats": {},
        }
    )
