# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-08-04

### Added

- Phase-1 foundation: OpenAI-compatible LLM client (`llm.py`), Pydantic
  output contracts with `json_repair` fallback (`schemas.py`), hand-written
  memory tools with a JSON-string contract (`tools.py`), and a generic
  tool-calling agent loop (`agent_loop.py`).
- Phase-2 agent roles (`agents/`): memory agent (session transcripts →
  topic-classified `.md`, read-then-merge, never overwrite), recall agent
  (query → `## 記憶上下文` context block with per-session cache and 5s
  timeout), index agent (INDEX.md + per-document `## Related` blocks,
  idempotent reindex), and reader agent (document → summary + topics).
- Versioned system prompts (`prompts/*.md`, loaded via `prompts.py`).
- Phase-3 Hermes integration (issues #10–#12): `provider.py`
  (`TabulariusMemoryProvider` — real-time daemon extraction on
  `on_session_end`, recall `prefetch`/`queue_prefetch` with timeout, built-in
  memory mirror on `on_memory_write` (add only), concurrency safety via
  daemon writer tracking + atomic snapshots + cross-process idempotent
  commits + atexit drain), `state.py` (`tabularius_state.json` —
  committed_sessions / last_reindex / extraction_stats), `sessions.py`
  (read-only schema-tolerant state.db scanning), and `cli.py` (`hermes
  tabularius status/setup/update/init/reindex`; `init --force` migrates
  history in batches of 5, backs up memory entries to
  `memory/archive/pre-init-<ts>.json`, and switches MEMORY.md to the
  INDEX.md pointer while keeping USER.md).
- Docker E2E suite (issue #18, `tests/e2e/`): verifies the plugin inside
  the real `nousresearch/hermes-agent` container — provider discovery
  (`hermes memory status`), CLI wiring, offline `status`/`setup`/`init`
  dry-run, provider availability + `chat -q` non-crash, and full
  `init --force` extraction (Level 4, gated on `TABULARIUS_API_KEY`).
  Driven by `Dockerfile.test` (build-time deps — `/opt/hermes` is immutable
  at runtime) + a session-scoped image fixture in `tests/e2e/conftest.py`.
- Test suite grown to 151 tests (138 unit + 13 Docker E2E) +
  pre-commit gates (black / ruff / mypy) + GitHub Actions CI (unit matrix
  + Docker E2E job).

### Changed

- Simplified phase-3 internals: shared `_drain_workers` join loop (was
  duplicated in `_drain_writers` / `_drain_all_writers`), shared
  `_recall_context` (was duplicated in `prefetch` / `queue_prefetch`),
  and a shared `make_state_db` test fixture.

### Fixed

- Recall: a timed-out first call no longer loses the session preload —
  the session resets so the next call re-preloads the most-used documents.
- Index: `## Related` stripping only removes the auto-generated trailing
  block; documents that legitimately contain the text mid-content are
  preserved.
- Provider: `handle_tool_call` no longer raises on malformed model args
  (wrong types / extra keys) — every exception becomes the standard error
  JSON, matching the tools-never-raise contract.
- Sessions: the read-only `state.db` `file:` URI is now percent-encoded —
  paths containing `#` / `?` previously opened the wrong store.
- Provider: concurrent memory mirrors (e.g. foreground turn + background
  self-review) are serialized so an update is never lost.
- Provider: transcript formatting handles dict message content instead of
  crashing.
