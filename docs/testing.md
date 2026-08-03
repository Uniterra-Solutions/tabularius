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
|| `test_agents_memory.py` | Issue #7: transcript batch → output; merge preserves old content; prompt versioned |
|| `test_agents_recall.py` | Issue #8: first-call preload; cache prevents re-read; timeout → empty context |
|| `test_agents_index.py` | Issue #9: INDEX.md + Related blocks; gap fill; reindex idempotent |
|| `test_agents_reader.py` | Issue #9: doc → summary; missing/traversal → `ToolError` |
|| `test_provider.py` | Issue #10: session-end extraction (non-blocking, idempotent), concurrent sync_turn, prefetch/queue_prefetch, memory mirror, tool surface, shutdown/atexit |
|| `test_state.py` | Issue #11: state.json roundtrip, corrupt fallback, committed/extraction/reindex records, legacy archive |
|| `test_sessions.py` | Issue #12: state.db scan oldest-first, unprocessed diff, transcript render, schema tolerance |
|| `test_cli.py` | Issues #11–#12: parser, status output, setup activation, init dry-run + force migration, reindex, backup/clear helpers |
| `e2e/test_install.py` | Docker L1: provider discovery (`memory status`), CLI wiring gated on `memory.provider` |
| `e2e/test_cli.py` | Docker L2: status / setup / init dry-run against a seeded state.db, no LLM key |
| `e2e/test_provider.py` | Docker L3: availability with relay key, `chat -q` fails only on inference provider (no plugin crash) |
| `e2e/test_extraction.py` | Docker L4: `init --force` full extraction + reindex — **skipped without `TABULARIUS_API_KEY`** |

Agent tests share scripted-LLM fakes in `tests/fakes.py` (duck-typed
`LLMClient` recording messages + tools; per-schema JSON builders).

## Docker E2E Tests (`tests/e2e/`)

Verifies the plugin inside the real `nousresearch/hermes-agent` container:
Hermes discovers tabularius as a memory provider, the CLI is wired, and the
plugin loads without breaking Hermes. Run with the full suite:

```bash
uv run pytest tests/ -q            # includes e2e (skipped if docker missing)
uv run pytest tests/e2e/ -q        # just the Docker layer
```

**Key files:**

- `Dockerfile.test` — derived image: `FROM nousresearch/hermes-agent:latest`
  + build-time `uv pip install` of `json-repair`, `fabricium`, and the repo
  package. **Never pip-install at runtime** — `/opt/hermes` is immutable in
  the published image.
- `tests/e2e/conftest.py` — session-scoped image build, per-test temp
  HERMES_HOME (plugin shim + `memory.provider: tabularius` config), and a
  `run_hermes` helper that mounts the home at `/opt/data` and runs a command.

**Test levels:**

| Level | Covers | Needs LLM key? |
|-------|--------|----------------|
| 1. Install smoke | `hermes memory status` lists tabularius active; CLI discovered | No |
| 2. CLI offline | `status` / `setup` / `init` dry-run with seeded state.db | No |
| 3. Provider lifecycle | availability with `TABULARIUS_API_KEY`, `chat -q` never crashes on plugin load | No |
| 4. Full extraction | `init --force` writes memory docs + `tabularius_state.json` | **Yes** — skipped without key |

**Key facts (verified against the image):**

- Memory providers are discovered from `$HERMES_HOME/plugins/<name>/` via a
  source heuristic (`register_memory_provider` / `MemoryProvider`) — not the
  generic `plugin.yaml` scan, so tabularius never appears in
  `hermes plugins list`; `hermes memory status` is the discovery check.
- CLI wiring is gated on `memory.provider: tabularius` in config.yaml —
  pre-write that in the mounted HERMES_HOME (no need to run `config set`).
- `chat -q` without an inference provider exits 1 with a Hermes-level
  message; the assertion is *no plugin traceback*, not a specific string.

**Environment:** the `e2e_image` fixture `pytest.skip`s the suite when
docker is missing or the base hermes-agent image isn't pulled locally, so
`uv run pytest tests/` stays green on machines without Docker. Level 4 is
additionally skipped unless `TABULARIUS_API_KEY` is set.

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
- `test_handle_tool_call_bad_args_returns_error_json` (review: malformed
  model args must never raise)
- `test_scan_handles_special_chars_in_db_path` (review: `file:` URI
  percent-encoding)
- `test_concurrent_mirrors_do_not_lose_updates` (review: serialized mirror
  read-modify-write)
- `test_dict_content_does_not_raise` (review: transcript formatting)
