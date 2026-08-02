# Testing

## Commands

```bash
# Full suite
uv run pytest tests/ -q

# Single file / single test
uv run pytest tests/test_tools.py -q
uv run pytest tests/test_agent_loop.py::TestRunAgent::test_no_tool_direct_json -q

# Collect-only (get real counts, never trust stale docs)
uv run pytest tests/ --collect-only -q | tail -1
```

Prepend `unset PYTHONPATH` when running under the Hermes desktop — its
PYTHONPATH shadows the project venv.

## Test Layout

| File | Covers |
|------|--------|
| `test_schemas.py` | Every Pydantic model (valid + invalid); `parse_or_retry` incl. json_repair fallback |
| `test_llm.py` | API key resolution order; JSON suffix injection; transient retry (429/5xx/timeout/4xx) |
| `test_tools.py` | Each tool on a real tmp dir; merge semantics; traversal rejection; atomic writes |
| `test_agent_loop.py` | No-tool direct JSON; two-round tool flow; schema retry; dispatch errors; round limit |
| `test_agents_memory.py` | Issue #7: transcript batch → output; merge preserves old content; prompt versioned |
| `test_agents_recall.py` | Issue #8: first-call preload; cache prevents re-read; timeout → empty context |
| `test_agents_index.py` | Issue #9: INDEX.md + Related blocks; gap fill; reindex idempotent |
| `test_agents_reader.py` | Issue #9: doc → summary; missing/traversal → `ToolError` |

Agent tests share scripted-LLM fakes in `tests/fakes.py` (duck-typed
`LLMClient` recording messages + tools; per-schema JSON builders).

## Fixtures

- `memory_root` (conftest.py) — points the memory dir at a real tmp dir via
  `HERMES_HOME` monkeypatch, creates it. Every tools test uses it.

## Mock Policy

- **Minimal mocking.** Tests use real temp dirs and real file I/O — no
  filesystem mocks.
- **LLM calls are scripted fakes.** `_FakeOpenAI` (test_llm.py) records
  kwargs and raises scripted exceptions to exercise retry;
  `_ScriptedClient` (test_agent_loop.py) returns scripted responses and
  records every messages list. No network in tests.
- **Agent loop stubbed by monkeypatch** where a tool test only needs the
  tool boundary (`spawn_reader` tests patch
  `tabularius.agent_loop.run_agent`).

## Evidence Tests

A test written for a specific bug is named after it and must FAIL on the
pre-fix code and PASS on the post-fix code:

- `test_nul_byte_path_returns_error_json`
- `test_write_to_existing_directory_returns_error_json`
- `test_write_when_parent_is_file_returns_error_json`
- `test_none_system_content_does_not_raise`
- `test_empty_choices_raises_clear_error`
