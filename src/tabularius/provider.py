"""Hermes MemoryProvider integration for tabularius (issue #10).

The provider plugs tabularius's agent roles into the Hermes MemoryManager:

- ``on_session_end`` spawns a **daemon extraction thread** (non-blocking) that
  runs the memory agent on the session transcript, merge-writes .md
  documents, then records the session in ``tabularius_state.json`` so a
  Hermes restart never re-extracts it (idempotent, cross-process).
- ``prefetch`` / ``queue_prefetch`` run the recall agent (5s timeout, empty
  on failure) and return the context block for prompt injection.
- ``on_memory_write`` mirrors built-in ``add`` writes to .md files without
  an agent call.
- ``shutdown`` + an atexit safety net drain in-flight writers
  (timeout-bounded, never hang).

Concurrency follows the OpenViking lessons: a daemon writer thread tracked
in ``_inflight_writers`` keyed by session id, ``_session_state_lock`` for
atomic snapshots (no lost turns), timeout-bounded ``_drain_writers``, and
commits persisted in ``tabularius_state.json`` (cross-process, unlike
OpenViking's in-memory record).

The class subclasses ``agent.memory_provider.MemoryProvider`` when running
inside Hermes; when imported standalone (unit tests, packaging) it degrades
to a plain object with the same surface.
"""

from __future__ import annotations

import atexit
import json
import logging
import threading
import time
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from agent.memory_provider import MemoryProvider as _MemoryProviderBase
else:
    try:
        from agent.memory_provider import MemoryProvider as _MemoryProviderBase
    except ImportError:  # standalone library / unit tests without Hermes
        _MemoryProviderBase = object  # type: ignore[assignment,misc]

from tabularius.agents.memory import run_memory_agent
from tabularius.agents.recall import RecallSession, run_recall_agent
from tabularius.llm import LLMClient, resolve_api_key
from tabularius.schemas import MemoryAgentOutput
from tabularius.state import (
    is_session_committed,
    record_extraction,
)
from tabularius.tools import (
    TOOL_REGISTRY,
    TOOL_SCHEMAS,
    memory_dir,
    memory_read,
    memory_write,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "tabularius"
RECALL_TIMEOUT = 5.0
SESSION_DRAIN_TIMEOUT = 10.0
_WRITER_JOIN_FLOOR = 0.05

# Built-in memory ``target`` -> mirror document name.
MIRROR_PATHS = {"memory": "agent-notes.md", "user": "user-profile.md"}
DEFAULT_MIRROR_PATH = "agent-notes.md"

# Tools exposed to the main agent. ``index_update`` / ``spawn_reader`` are
# internal to init/reindex and stay out of the conversation toolset.
PROVIDER_TOOL_NAMES = ("memory_read", "memory_write", "memory_list")


def _format_turn(user_content: str, assistant_content: str) -> str:
    return f"## user\n{user_content}\n\n## assistant\n{assistant_content}"


def _message_text(message: dict[str, Any]) -> str | None:
    """Render one OpenAI-style message as transcript text (None to skip)."""
    content = message.get("content") or ""
    if isinstance(content, list):  # some providers send content parts
        content = " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    if content.strip():
        return str(content)
    calls = message.get("tool_calls")
    if isinstance(calls, list) and calls:
        names = [
            str(call.get("function", {}).get("name", "?"))
            for call in calls
            if isinstance(call, dict)
        ]
        return "[tool_calls: " + ", ".join(names) + "]"
    return None


def format_messages(messages: list[dict[str, Any]]) -> str:
    """Render a Hermes conversation message list as a transcript string."""
    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "?")).strip() or "?"
        text = _message_text(message)
        if text is None:
            continue
        parts.append(f"## {role}\n{text}")
    return "\n\n".join(parts)


def _mirror_entry(target: str, content: str) -> None:
    """Append a built-in memory entry to its mirror document (deduped)."""
    path = MIRROR_PATHS.get(target, DEFAULT_MIRROR_PATH)
    bullet = "- " + content.strip().replace("\n", "\n  ") + "\n"
    read = json.loads(memory_read(path))
    if read.get("ok"):
        current: str = read["content"]
        if content.strip() in current:
            return  # exact duplicate — matches the built-in dedupe
        write = json.loads(memory_write(path, f"{current.rstrip()}\n{bullet}", "merge"))
    else:
        write = json.loads(memory_write(path, bullet, "create"))
    if not write.get("ok"):
        logger.debug("tabularius memory mirror write failed: %s", write.get("error"))


# ---------------------------------------------------------------------------
# Process-level atexit safety net — drains in-flight writers so an
# already-started extraction lands even if shutdown() is never called
# (gateway crash, exception in the session watcher). Pending-but-unstarted
# sessions are recovered by ``tabularius init`` (cross-process scan).
# ---------------------------------------------------------------------------

_last_active_provider: "TabulariusMemoryProvider | None" = None
_last_active_lock = threading.Lock()


def _set_last_active(provider: "TabulariusMemoryProvider") -> None:
    global _last_active_provider
    with _last_active_lock:
        _last_active_provider = provider


def _clear_last_active(provider: "TabulariusMemoryProvider") -> None:
    global _last_active_provider
    with _last_active_lock:
        if _last_active_provider is provider:
            _last_active_provider = None


def _atexit_commit_pending() -> None:
    global _last_active_provider
    with _last_active_lock:
        provider = _last_active_provider
        _last_active_provider = None
    if provider is None:
        return
    try:
        provider._drain_all_writers(SESSION_DRAIN_TIMEOUT)
    except Exception:  # best-effort at shutdown time
        pass


atexit.register(_atexit_commit_pending)


class TabulariusMemoryProvider(_MemoryProviderBase):
    """MemoryProvider wiring tabularius agents to Hermes conversations."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client
        self._session_id = ""
        self._shutting_down = False

        # Serializes session state snapshots (prevents lost turns).
        self._session_state_lock = threading.Lock()
        # Buffered turns per session (fallback transcript when
        # on_session_end receives an empty message list).
        self._pending_turns: dict[str, list[str]] = {}

        # Daemon writer tracking, keyed by session id.
        self._inflight_lock = threading.Lock()
        self._inflight_writers: dict[str, set[threading.Thread]] = {}

        # Recall-agent caches.
        self._recall_sessions: dict[str, RecallSession] = {}
        self._prefetch_lock = threading.Lock()
        self._prefetch_results: dict[str, str] = {}

    # -- Core lifecycle -----------------------------------------------------

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def is_available(self) -> bool:
        """Available when a relay API key is configured (no network calls)."""
        try:
            resolve_api_key()
            return True
        except RuntimeError:
            return False

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        # The hermes_home kwarg is deliberately ignored: every path resolves
        # through fabricium's global home (tools.memory_dir / state.state_path).
        self._session_id = str(session_id or "")
        _set_last_active(self)

    # -- Turn / session handling ---------------------------------------------

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        """Buffer the completed turn (cheap, in-memory) under the lock."""
        sid = session_id or self._session_id
        with self._session_state_lock:
            if sid:
                self._pending_turns.setdefault(sid, []).append(
                    _format_turn(str(user_content or ""), str(assistant_content or ""))
                )

    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        """Trigger real-time extraction on a daemon thread (non-blocking)."""
        if self._shutting_down:
            return
        with self._session_state_lock:
            sid = self._session_id
            transcript = self._snapshot_transcript_locked(messages)
        if not transcript.strip():
            return
        if is_session_committed(sid):
            return
        self._spawn_writer(
            sid, lambda: self._extract_and_commit(sid, transcript), "tabularius-extract"
        )

    def _snapshot_transcript_locked(self, messages: list[dict[str, Any]]) -> str:
        """Build the session transcript atomically against concurrent sync_turn.

        A real message list is authoritative and clears the buffer (the
        buffer duplicates those turns); an empty list (atexit / edge cases)
        falls back to the buffered turns so nothing is lost.
        """
        if messages:
            self._pending_turns.pop(self._session_id, None)
            return format_messages(messages)
        turns = self._pending_turns.pop(self._session_id, [])
        return "\n\n".join(turns)

    def _extract_and_commit(self, session_id: str, transcript: str) -> None:
        """Run the memory agent and record the session as committed."""
        try:
            if is_session_committed(session_id):
                return
            output: MemoryAgentOutput = run_memory_agent([transcript], client=self._client)
            failures = 0
            for doc in output.documents:
                write = json.loads(memory_write(doc.path, doc.content, doc.action))
                if not write.get("ok"):
                    failures += 1
                    logger.warning(
                        "tabularius extraction write failed for %s: %s",
                        doc.path,
                        write.get("error"),
                    )
            if failures:
                return  # partial write — leave uncommitted so init retries
            record_extraction(session_id, output.stats)
        except Exception as exc:
            logger.warning("tabularius extraction failed for %s: %s", session_id, exc)

    # -- Recall ---------------------------------------------------------------

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Return recall context for the upcoming turn (timeout-bounded).

        Consumes a background result queued by ``queue_prefetch`` when one
        is available; otherwise runs the recall agent synchronously under
        its short timeout. Any failure returns an empty string so recall
        never blocks the conversation.
        """
        sid = session_id or self._session_id
        with self._prefetch_lock:
            cached = self._prefetch_results.pop(sid, None)
        if cached is not None:
            return cached
        try:
            return self._recall_context(sid, query)
        except Exception as exc:
            logger.debug("tabularius prefetch failed: %s", exc)
            return ""

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """Warm the next turn's recall on a daemon thread."""
        sid = session_id or self._session_id

        def _recall() -> None:
            try:
                context = self._recall_context(sid, query)
            except Exception as exc:
                logger.debug("tabularius queued prefetch failed: %s", exc)
                return
            with self._prefetch_lock:
                if not self._shutting_down:
                    self._prefetch_results[sid] = context

        self._spawn_writer(sid, _recall, "tabularius-prefetch")

    def _recall_context(self, sid: str, query: str) -> str:
        """Run the recall agent for ``sid`` and return its context block."""
        session = self._recall_sessions.setdefault(sid, RecallSession())
        output = run_recall_agent(
            query, session=session, client=self._client, timeout=RECALL_TIMEOUT
        )
        return output.context_block

    # -- Built-in memory mirror -----------------------------------------------

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Mirror built-in memory ``add`` writes to .md (daemon, no agent)."""
        if action != "add" or not content:
            return
        self._spawn_writer(
            self._session_id, lambda: _mirror_entry(target, content), "tabularius-memwrite"
        )

    # -- Tools ----------------------------------------------------------------

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            schema
            for schema in TOOL_SCHEMAS
            if schema.get("function", {}).get("name") in PROVIDER_TOOL_NAMES
        ]

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> str:
        tool = TOOL_REGISTRY.get(tool_name) if tool_name in PROVIDER_TOOL_NAMES else None
        if tool is None:
            return json.dumps({"ok": False, "error": f"unknown tool: {tool_name}"})
        return tool(**args)

    # -- Teardown ---------------------------------------------------------------

    def shutdown(self) -> None:
        self._shutting_down = True
        self._drain_all_writers(SESSION_DRAIN_TIMEOUT)
        _clear_last_active(self)

    def backup_paths(self) -> list[str]:
        """Declare the memory directory + state file for ``hermes backup``."""
        return [str(memory_dir()), str(memory_dir().parent / "tabularius_state.json")]

    # -- Writer plumbing (OpenViking-style) -----------------------------------

    def _spawn_writer(self, sid: str, target: Callable[[], None], name: str) -> None:
        """Start a daemon writer tracked in ``_inflight_writers[sid]``."""
        holder: list[threading.Thread] = []

        def _wrapped() -> None:
            try:
                target()
            finally:
                with self._inflight_lock:
                    workers = self._inflight_writers.get(sid)
                    if workers is not None:
                        workers.discard(holder[0])
                        if not workers:
                            self._inflight_writers.pop(sid, None)

        thread = threading.Thread(target=_wrapped, daemon=True, name=name)
        holder.append(thread)
        with self._inflight_lock:
            if self._shutting_down:
                return
            self._inflight_writers.setdefault(sid, set()).add(thread)
        thread.start()

    def _drain_writers(self, sid: str, timeout: float) -> bool:
        """Join every in-flight writer for ``sid`` within ``timeout``.

        Returns True if all drained; a False return (still alive) makes the
        caller skip instead of hang.
        """

        def _workers() -> list[threading.Thread]:
            with self._inflight_lock:
                return list(self._inflight_writers.get(sid, ()))

        return _drain_workers(_workers, timeout)

    def _drain_all_writers(self, timeout: float) -> bool:
        """Join every in-flight writer across all sessions within ``timeout``."""

        def _workers() -> list[threading.Thread]:
            with self._inflight_lock:
                return [t for workers in self._inflight_writers.values() for t in workers]

        return _drain_workers(_workers, timeout)


def _drain_workers(get_workers: Callable[[], list[threading.Thread]], timeout: float) -> bool:
    """Join live workers from ``get_workers`` within ``timeout``.

    Re-fetches the worker list each loop because finished writers remove
    themselves asynchronously. Returns True if all drained; False (still
    alive) makes the caller skip instead of hang.
    """
    deadline = time.monotonic() + timeout
    while True:
        workers = [t for t in get_workers() if t.is_alive()]
        if not workers:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        for t in workers:
            slice_left = deadline - time.monotonic()
            if slice_left <= 0:
                break
            t.join(timeout=min(slice_left, _WRITER_JOIN_FLOOR))


def create_provider(client: LLMClient | None = None) -> TabulariusMemoryProvider:
    """Instantiate the provider (used by ``register`` and tests)."""
    return TabulariusMemoryProvider(client=client)


__all__ = [
    "PROVIDER_NAME",
    "TabulariusMemoryProvider",
    "create_provider",
    "format_messages",
]
