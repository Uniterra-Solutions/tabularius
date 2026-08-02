# Project Structure

```
tabularius/
├── AGENTS.md              # Build/test commands, constraints, boundaries
├── LICENSE                # MIT, Copyright Lai Tsz Kin
├── README.md              # One-line positioning
├── pyproject.toml         # hatchling, deps, ruff/mypy/pytest config
├── uv.lock                # Locked dependency graph
├── src/tabularius/
│   ├── __init__.py        # Package metadata (__version__)
│   ├── cli.py             # CLI entry points (init / reindex) — later phase
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
├── tests/
│   ├── conftest.py        # sys.path fix + memory_root fixture
│   ├── fakes.py           # Shared scripted-LLM fakes for agent tests
│   ├── test_llm.py        # API key, JSON prompt, retry logic
│   ├── test_schemas.py    # Model contracts + parse_or_retry
│   ├── test_tools.py      # Tools: real tmp dirs, merge, traversal
│   ├── test_agent_loop.py # Loop flows: tools, retry, dispatch
│   └── test_agents_*.py   # memory / recall / index / reader roles
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
| `tests/conftest.py` | Hermes PYTHONPATH fix; `memory_root` tmp-dir fixture |
| `tests/fakes.py` | Shared scripted-LLM fakes (messages + tools recording) |
| `tests/test_*.py` | One file per source module, mirroring names |

## Placeholders (later phases)

- `cli.py` — `init` / `reindex` (phase 3, issue #12)
- `__init__.py` — will grow `register(ctx)` for MemoryProvider (phase 3,
  issues #10–#11)
