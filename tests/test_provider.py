"""Tests for provider.py — Hermes MemoryProvider integration (issue #10)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from fakes import _FakeMessage, _FakeResponse, _ScriptedClient, recall_output_json

import tabularius
from tabularius import state as tabularius_state
from tabularius.provider import (
    TabulariusMemoryProvider,
    _atexit_commit_pending,
    create_provider,
    format_messages,
)

_CREATE_OUTPUT = json.dumps(
    {
        "documents": [{"action": "create", "path": "a.md", "content": "# A\n", "reason": "r"}],
        "processed_sessions": ["sess-1"],
        "stats": {"docs": 1, "sessions": 1},
    }
)


class _Ctx:
    def __init__(self) -> None:
        self.provider = None

    def register_memory_provider(self, provider: TabulariusMemoryProvider) -> None:
        self.provider = provider


class _RaisingClient:
    def chat(self, messages, tools=None, timeout=None):
        raise RuntimeError("boom")


class TestRegistration:
    def test_register_registers_provider(self) -> None:
        ctx = _Ctx()
        tabularius.register(ctx)
        assert ctx.provider is not None
        assert ctx.provider.name == "tabularius"

    def test_register_ignores_foreign_context(self) -> None:
        tabularius.register(object())  # no exception, no provider captured

    def test_init_source_detected_as_memory_provider(self) -> None:
        """Hermes' discovery heuristic scans __init__.py for the markers."""
        source = Path(tabularius.__file__).read_text(encoding="utf-8")
        assert "register_memory_provider" in source or "MemoryProvider" in source


class TestAvailability:
    def test_not_available_without_key(self, monkeypatch) -> None:
        monkeypatch.delenv("TABULARIUS_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert create_provider().is_available() is False

    def test_available_with_key(self, monkeypatch) -> None:
        monkeypatch.setenv("TABULARIUS_API_KEY", "test-key")
        assert create_provider().is_available() is True


class TestSessionEnd:
    def test_on_session_end_extracts_and_commits(self, memory_root) -> None:
        client = _ScriptedClient([_FakeResponse(_FakeMessage(_CREATE_OUTPUT))])
        provider = create_provider(client=client)  # type: ignore[arg-type]
        provider.initialize("sess-1", hermes_home=str(memory_root.parent))

        provider.on_session_end(
            [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        )
        assert provider._drain_writers("sess-1", 5.0)

        assert (memory_root / "a.md").read_text(encoding="utf-8") == "# A\n"
        assert tabularius_state.is_session_committed("sess-1")
        stats = tabularius_state.load_state()["extraction_stats"]["sess-1"]
        assert stats["docs"] == 1

    def test_on_session_end_is_non_blocking(self, memory_root) -> None:
        """The call returns before the daemon extraction thread finishes."""
        started = threading.Event()
        release = threading.Event()

        class _SlowClient:
            def chat(self, messages, tools=None, timeout=None):
                started.set()
                assert release.wait(timeout=5)
                return _FakeResponse(_FakeMessage(_CREATE_OUTPUT))

        provider = create_provider(client=_SlowClient())  # type: ignore[arg-type]
        provider.initialize("sess-1")

        provider.on_session_end([{"role": "user", "content": "hello"}])
        # returns while the daemon extraction is still blocked in the LLM call
        assert started.wait(2.0)
        with provider._inflight_lock:
            pending = provider._inflight_writers.get("sess-1", set())
        assert pending, "extraction must run on a tracked daemon thread"
        release.set()
        assert provider._drain_writers("sess-1", 5.0)

    def test_on_session_end_uses_buffered_turns_when_messages_empty(self, memory_root) -> None:
        client = _ScriptedClient([_FakeResponse(_FakeMessage(_CREATE_OUTPUT))])
        provider = create_provider(client=client)  # type: ignore[arg-type]
        provider.initialize("sess-1")
        provider.sync_turn("q", "a", session_id="sess-1")

        provider.on_session_end([])  # atexit-style empty message list
        assert provider._drain_writers("sess-1", 5.0)
        assert tabularius_state.is_session_committed("sess-1")

    def test_second_session_end_is_idempotent(self, memory_root) -> None:
        client = _ScriptedClient([_FakeResponse(_FakeMessage(_CREATE_OUTPUT))])
        provider = create_provider(client=client)  # type: ignore[arg-type]
        provider.initialize("sess-1")

        provider.on_session_end([{"role": "user", "content": "hello"}])
        assert provider._drain_writers("sess-1", 5.0)
        provider.on_session_end([{"role": "user", "content": "hello"}])
        assert provider._drain_writers("sess-1", 5.0)

        assert len(client.messages_seen) == 1  # extraction ran exactly once
        assert (memory_root / "a.md").read_text(encoding="utf-8") == "# A\n"

    def test_partial_write_failure_skips_commit(self, memory_root) -> None:
        # merge into a file that does not exist → write failure → no commit
        bad = json.dumps(
            {
                "documents": [
                    {"action": "merge", "path": "missing.md", "content": "x", "reason": "r"}
                ],
                "processed_sessions": ["sess-1"],
                "stats": {"docs": 1, "sessions": 1},
            }
        )
        client = _ScriptedClient([_FakeResponse(_FakeMessage(bad))])
        provider = create_provider(client=client)  # type: ignore[arg-type]
        provider.initialize("sess-1")

        provider.on_session_end([{"role": "user", "content": "hello"}])
        assert provider._drain_writers("sess-1", 5.0)
        assert not tabularius_state.is_session_committed("sess-1")


class TestConcurrency:
    def test_concurrent_sync_turns_not_lost(self, memory_root) -> None:
        provider = create_provider()
        provider.initialize("sess-1")
        turn_count = 30

        def _sync(index: int) -> None:
            provider.sync_turn(f"user {index}", f"asst {index}", session_id="sess-1")

        threads = [threading.Thread(target=_sync, args=(i,)) for i in range(turn_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with provider._session_state_lock:
            transcript = provider._snapshot_transcript_locked([])
        for i in range(turn_count):
            assert f"user {i}" in transcript
            assert f"asst {i}" in transcript

    def test_extraction_agent_sees_merged_transcript(self, memory_root) -> None:
        client = _ScriptedClient([_FakeResponse(_FakeMessage(_CREATE_OUTPUT))])
        provider = create_provider(client=client)  # type: ignore[arg-type]
        provider.initialize("sess-1")
        provider.sync_turn("first q", "first a", session_id="sess-1")
        provider.sync_turn("second q", "second a", session_id="sess-1")

        provider.on_session_end([])
        assert provider._drain_writers("sess-1", 5.0)
        user_prompt = client.messages_seen[0][1]["content"]
        assert "first q" in user_prompt
        assert "second q" in user_prompt


class TestPrefetch:
    def test_prefetch_returns_context_block(self, memory_root) -> None:
        client = _ScriptedClient([_FakeResponse(_FakeMessage(recall_output_json()))])
        provider = create_provider(client=client)  # type: ignore[arg-type]
        provider.initialize("sess-1")
        ctx = provider.prefetch("what do we know about vps?", session_id="sess-1")
        assert "relevant facts" in ctx

    def test_prefetch_failure_returns_empty(self, memory_root) -> None:
        provider = create_provider(client=_RaisingClient())  # type: ignore[arg-type]
        provider.initialize("sess-1")
        assert provider.prefetch("query", session_id="sess-1") == ""

    def test_queue_prefetch_warms_next_turn(self, memory_root) -> None:
        client = _ScriptedClient([_FakeResponse(_FakeMessage(recall_output_json()))])
        provider = create_provider(client=client)  # type: ignore[arg-type]
        provider.initialize("sess-1")
        provider.queue_prefetch("query", session_id="sess-1")
        assert provider._drain_writers("sess-1", 5.0)
        ctx = provider.prefetch("query", session_id="sess-1")
        assert "relevant facts" in ctx
        # the queued result is consumed — nothing left for the next turn
        assert provider._prefetch_results.get("sess-1") is None


class TestMemoryMirror:
    def test_mirrors_add_to_markdown(self, memory_root) -> None:
        provider = create_provider()
        provider.initialize("sess-1")
        provider.on_memory_write("add", "memory", "Some durable note")
        provider.on_memory_write("add", "user", "User prefers X")
        assert provider._drain_writers("sess-1", 5.0)

        notes = (memory_root / "agent-notes.md").read_text(encoding="utf-8")
        profile = (memory_root / "user-profile.md").read_text(encoding="utf-8")
        assert "Some durable note" in notes
        assert "User prefers X" in profile

    def test_mirror_dedupes_exact_duplicates(self, memory_root) -> None:
        provider = create_provider()
        provider.initialize("sess-1")
        provider.on_memory_write("add", "memory", "Dup note")
        provider.on_memory_write("add", "memory", "Dup note")
        assert provider._drain_writers("sess-1", 5.0)

        content = (memory_root / "agent-notes.md").read_text(encoding="utf-8")
        assert content.count("Dup note") == 1

    def test_non_add_actions_ignored(self, memory_root) -> None:
        provider = create_provider()
        provider.initialize("sess-1")
        provider.on_memory_write("replace", "memory", "nope")
        provider.on_memory_write("remove", "memory", "nope")
        provider.on_memory_write("add", "memory", "")
        assert provider._drain_writers("sess-1", 5.0)
        assert not (memory_root / "agent-notes.md").exists()


class TestTools:
    def test_tool_schemas_are_subset(self) -> None:
        names = {schema["function"]["name"] for schema in create_provider().get_tool_schemas()}
        assert names == {"memory_read", "memory_write", "memory_list"}

    def test_handle_tool_call_dispatches(self, memory_root) -> None:
        provider = create_provider()
        result = json.loads(provider.handle_tool_call("memory_read", {"path": "missing.md"}))
        assert result["ok"] is False

    def test_handle_tool_call_rejects_internal_tools(self, memory_root) -> None:
        provider = create_provider()
        result = json.loads(provider.handle_tool_call("spawn_reader", {"path": "a.md"}))
        assert result["ok"] is False
        result = json.loads(provider.handle_tool_call("index_update", {"entries": []}))
        assert result["ok"] is False

    def test_handle_tool_call_unknown(self) -> None:
        provider = create_provider()
        result = json.loads(provider.handle_tool_call("nope", {}))
        assert result["ok"] is False


class TestTeardown:
    def test_shutdown_drains_writers(self, memory_root) -> None:
        provider = create_provider()
        provider.initialize("sess-1")
        provider.on_memory_write("add", "memory", "late note")
        provider.shutdown()
        assert (memory_root / "agent-notes.md").read_text(encoding="utf-8") == ("- late note\n")

    def test_atexit_commits_pending(self, memory_root) -> None:
        provider = create_provider()
        provider.initialize("sess-1")
        provider.on_memory_write("add", "memory", "exit note")
        _atexit_commit_pending()
        assert (memory_root / "agent-notes.md").read_text(encoding="utf-8") == "- exit note\n"

    def test_backup_paths(self, memory_root) -> None:
        paths = create_provider().backup_paths()
        assert str(memory_root) in paths
        assert any("tabularius_state.json" in path for path in paths)


class TestFormatMessages:
    def test_renders_roles_and_skips_empty(self) -> None:
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "f"}}]},
            {"role": "tool", "content": ""},
            {"role": "assistant", "content": "done"},
        ]
        text = format_messages(messages)
        assert "## user\nhello" in text
        assert "[tool_calls: f]" in text
        assert "## tool" not in text
        assert "## assistant\ndone" in text
