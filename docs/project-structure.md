# Project Structure

```
tabularius/
├── AGENTS.md              # Build/test commands, constraints, boundaries
├── LICENSE                # MIT, Copyright Lai Tsz Kin
├── README.md              # One-line positioning
├── pyproject.toml         # hatchling, deps, ruff/mypy/pytest config
├── uv.lock                # Locked dependency graph
├── src/tabularius/
│   ├── __init__.py        # register(ctx) → MemoryProvider (Hermes plugin entry)
│   ├── plugin.yaml        # Hermes plugin manifest (name: tabularius)
│   ├── provider.py        # MemoryProvider: on_session_end / prefetch / mirror
│   ├── state.py           # tabularius_state.json (committed_sessions, stats)
│   ├── sessions.py        # state.db scanning (read-only, schema tolerant)
│   ├── cli.py             # hermes tabularius status/setup/update/init/reindex
│   ├── llm.py             # OpenAI SDK wrapper → uniterra relay + retry
│   ├── schemas.py         # Pydantic output contracts + parse_or_retry
│   ├── tools.py           # Hand-written memory tools (JSON-string contract)
│   ├── prompts.py         # load_prompt + prompts/*.md (versioned system prompts)
│   ├── agent_loop.py      # Generic tool-calling loop (run_agent)
│   ├── prompts/           # Versioned role prompts (memory/recall/index/reader)
│   └── agents/            # Agent roles: memory / recall / index / reader
│       ├── __init__.py
│       ├── memory.py      # Transcripts → topic .md (merge, never overwrite)
│       ├── recall.py      # Query → context block (session cache, timeout)
│       ├── index.py       # INDEX.md + ## Related blocks (idempotent)
│       └── reader.py      # Document → summary + topics
├── stubs/
│   └── agent/memory_provider.pyi  # Mypy stub for the Hermes-only ABC
├── tests/
│   ├── conftest.py        # sys.path fix + memory_root fixture
│   ├── fakes.py           # Shared scripted-LLM fakes for agent tests
│   ├── test_llm.py        # API key, JSON prompt, retry logic
│   ├── test_schemas.py    # Model contracts + parse_or_retry
│   ├── test_tools.py      # Tools: real tmp dirs, merge, traversal
│   ├── test_agent_loop.py # Loop flows: tools, retry, dispatch
│   ├── test_agents_*.py   # memory / recall / index / reader roles
│   ├── test_provider.py   # Provider: session end, concurrency, mirror, tools
│   ├── test_state.py      # tabularius_state.json read/write (real tmp)
│   ├── test_sessions.py   # state.db scanning (schema tolerant)
│   ├── test_cli.py        # status / setup / init --dry-run / init --force / reindex
│   └── e2e/               # Docker E2E (L1 install, L2 CLI, L3 lifecycle, L4 extraction)
│       ├── conftest.py    # Image build + temp HERMES_HOME + run_hermes helper
│       ├── test_install.py    # Provider discovery, CLI wiring
│       ├── test_cli.py        # status/setup/init dry-run offline
│       ├── test_provider.py   # availability + chat never crashes
│       └── test_extraction.py # init --force full pipeline (needs API key)
├── Dockerfile.test        # Derived hermes-agent image for E2E (build-time deps)
└── docs/
    ├── README.md          # Docs index
    ├── architecture.md    # System context, data flow, decisions
    ├── conventions.md     # Naming, types, error handling, security
    ├── project-structure.md
    ├── tech-stack.md      # Versions, dep rationale
    ├── testing.md         # Commands, fixtures, mock policy
    └── modules/           # Per-module deep dives
```

## Responsibility Table

| Path | Responsibility |
|------|----------------|
| `src/tabularius/llm.py` | API key resolution, chat-completions wrapper, transient retry, JSON output constraints |
| `src/tabularius/schemas.py` | Agent output contracts; `parse_or_retry` with json_repair fallback |
| `src/tabularius/tools.py` | Memory-dir tools (`memory_read/write/list`, `index_update`, `spawn_reader`); `TOOL_SCHEMAS` + `TOOL_REGISTRY` |
| `src/tabularius/agent_loop.py` | `run_agent`: tool-calling loop, schema retry, dispatch (generic over output schema) |
| `src/tabularius/prompts.py` | `load_prompt` + `PROMPTS_DIR` — versioned role prompts |
| `src/tabularius/agents/` | memory / recall / index / reader roles on `run_agent` (issues #7–#9) |
| `src/tabularius/provider.py` | `TabulariusMemoryProvider` (issues #10): daemon extraction, prefetch, memory mirror, drain + atexit |
| `src/tabularius/state.py` | `tabularius_state.json` (issues #11): committed_sessions / last_reindex / extraction_stats |
| `src/tabularius/sessions.py` | state.db read-only scanning + transcript rendering (issue #12) |
| `src/tabularius/cli.py` | `hermes tabularius status/setup/update/init/reindex` (issues #11–#12) |
| `src/tabularius/plugin.yaml` | Hermes plugin manifest (memory-provider discovery) |
| `tests/conftest.py` | Hermes PYTHONPATH fix; `memory_root` tmp-dir fixture |
| `tests/fakes.py` | Shared scripted-LLM fakes (messages + tools recording) |
| `tests/test_*.py` | One file per source module, mirroring names |
| `tests/e2e/` | Docker E2E suite (L1–L4) — see `docs/testing.md` |
| `Dockerfile.test` | Derived `nousresearch/hermes-agent` image for E2E (build-time `uv pip install` of json-repair / fabricium / tabularius) |
