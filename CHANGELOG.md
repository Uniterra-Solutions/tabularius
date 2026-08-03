# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- Test suite (76 tests, real temp dirs, no network) + pre-commit gates
  (black / ruff / mypy) + GitHub Actions CI workflow.

### Fixed

- Recall: a timed-out first call no longer loses the session preload —
  the session resets so the next call re-preloads the most-used documents.
- Index: `## Related` stripping only removes the auto-generated trailing
  block; documents that legitimately contain the text mid-content are
  preserved.
