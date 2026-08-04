# Conventions

## Naming

| Scope | Convention | Example |
|-------|------------|---------|
| Modules/files | `snake_case` | `agent_loop.py`, `test_tools.py` |
| Classes | `PascalCase` | `LLMClient`, `MemoryAgentOutput` |
| Functions/methods | `snake_case` | `resolve_api_key()`, `_resolve_path()` |
| Private methods | `_leading_underscore` | `_atomic_write()`, `_is_transient()` |
| Constants | `UPPER_SNAKE` | `DEFAULT_BASE_URL`, `MAX_RETRIES` |
| Test files | `test_<module>.py` | `test_llm.py`, `test_tools.py` |
| Test classes | `Test<PascalCase>` | `TestMemoryWrite`, `TestChatRetry` |
| Test methods | `test_<behavior>` | `test_create_refuses_overwrite` |

## Imports

- Standard library first, then third-party, then local (ruff `I` rule).
- Absolute imports within tabularius: `from tabularius.llm import LLMClient`,
  not `from . import llm`.
- `from __future__ import annotations` at the top of every module.
- `Any` only where truly dynamic (tool JSON args, OpenAI SDK responses).

## Type Hints

- mypy `--strict` enforced on `src/tabularius`. All functions annotated.
- Use `| None` instead of `Optional[...]` (Python 3.10+).
- Prefer exact types over `Any` — e.g. `client: LLMClient | None` for the
  injectable client, not `client: Any`.

## Error Handling

- **Tools never raise on user input.** Every tool returns a JSON string:
  `{"ok": true, ...}` or `{"ok": false, "error": "..."}`. Exceptions
  (`ToolError`, `OSError`, `ValueError`) are translated to error JSON at
  the tool boundary.
- `ToolError(ValueError)` is raised internally by `_resolve_path()` for
  unsafe paths and caught by tools → error JSON.
- `SchemaParseError(ValueError)` is raised by `parse_or_retry()` when LLM
  content cannot be parsed/validated — the agent loop catches it to retry
  with corrective feedback.
- `OutputTruncatedError(RuntimeError)` is raised by `LLMClient.chat()` when
  `finish_reason=length` persists after the automatic `max_tokens` bumps —
  callers must never parse an empty/partial payload as if it were success.
- The agent loop wraps `dispatch()` in `except Exception` so a raising tool
  feeds back as error JSON to the model instead of crashing the run.

## Tool JSON Contract

Every tool signature returns `str` (JSON):

```json
{"ok": true, "path": "a.md", "content": "..."}   // success
{"ok": false, "error": "file not found: a.md"}    // failure
```

Rules:
- Success payload carries the tool-specific fields (see
  `docs/modules/tools.md`).
- Error strings are human/LLM-readable and preserve the reason (path,
  action, write failure detail).
- `ensure_ascii=False` — Chinese/markdown content round-trips unescaped.

## File I/O

- **Explicit `encoding="utf-8"`** on every `read_text` / `write_text`.
- **Atomic writes** via `tempfile.mkstemp` + `os.replace` in the same
  directory (`_atomic_write()`). No partial files on crash.
- **Memory dir resolved per call** through `_get_global_hermes_home()`
  (honors `HERMES_HOME`, no hardcoded `~/.hermes`).

## Security

- **Path traversal rejected** in `_resolve_path()`: resolve + check
  `is_relative_to(memory_root)`. Covers `..`, absolute paths, NUL bytes
  (`ValueError`), and symlink loops (`OSError`).
- **No secrets in code.** API key from `TABULARIUS_API_KEY` →
  `OPENAI_API_KEY`; missing key raises a clear `RuntimeError`.
- **LLM params are env-configurable.** `LLMClient` resolves `base_url` /
  `model` / `max_tokens` / `timeout` as explicit kwargs → `TABULARIUS_*`
  env vars → `DEFAULT_*` constants. Invalid numeric env values raise a
  `RuntimeError` naming the variable (never silently fall back).
- `.env` in `.gitignore` — never committed.

## Testing

- pytest with `tmp_path`-based fixtures; the `memory_root` fixture in
  `tests/conftest.py` points the memory dir at a real temp dir via
  `HERMES_HOME` monkeypatch.
- No network in unit tests — OpenAI calls are scripted fakes
  (`_ScriptedClient`, `_FakeOpenAI`).
- Evidence-test naming: a test for a specific bug is named after it
  (`test_nul_byte_path_returns_error_json`).
- Docker E2E lives in `tests/e2e/` (levels documented in `docs/testing.md`).
  The suite must skip cleanly when docker or the base hermes-agent image is
  missing — never fail a local `uv run pytest tests/` on machines without
  Docker. Real-LLM tests (Level 4) must be gated on `TABULARIUS_API_KEY`.
- E2E assertions check side effects and exit codes, never exact LLM output
  (non-deterministic).

## How to Update

- Convention added/changed? → Update the relevant row above.
- New naming pattern? → Add to the naming table.
- Linter rule changed? → Add to tool config first, then reflect here.
