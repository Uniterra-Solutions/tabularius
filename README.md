# Tabularius

Hermes MemoryProvider plugin: automatically extracts, indexes, and recalls
conversation memory as markdown.

Tabularius turns session transcripts into durable, topic-classified markdown
files in a profile-safe memory directory, and injects the relevant context
back into prompts before each LLM call.

## Status

- **Implemented**: phase-1 execution layer (LLM client, output schemas,
  memory tools, generic agent loop) and phase-2 agent roles (memory /
  recall / index / reader).
- **Upcoming**: MemoryProvider integration (`on_session_end` /
  `prefetch`), `tabularius init` / `reindex` CLI commands, and the
  `hermes memory setup` install flow (tracked as GitHub issues #10–#12).

## Requirements

- Python ≥ 3.10
- An API key for the Uniterra relay (`deepseek-v4-flash`)

## Install

```bash
# Clone, then install with uv (dev deps included)
uv sync --dev

# Or pip
pip install -e .
```

## Configuration

| Env var | Purpose |
|---------|---------|
| `TABULARIUS_API_KEY` | Relay API key (preferred) |
| `OPENAI_API_KEY` | Fallback API key |
| `HERMES_HOME` | Hermes home override (memory dir resolves to `~/.hermes/memory/` via fabricium) |

## Quickstart

Tabularius is a library of four agent roles, all driven by one hand-written
tool-calling loop:

```python
from tabularius.agents import (
    RecallSession,
    run_index_agent,
    run_memory_agent,
    run_recall_agent,
)

# 1. Extract memory from a batch of session transcripts (typically 5).
#    New information merges into existing topic files — never overwrites.
out = run_memory_agent([transcript_1, transcript_2, transcript_3, transcript_4, transcript_5])
# out.documents -> [{action: "merge"|"create", path, content, reason}]

# 2. Recall relevant memory before an LLM call. Pass the same RecallSession
#    for the whole conversation so files are only read once.
session = RecallSession()
ctx = run_recall_agent("what did we decide about the VPS?", session=session)
# ctx.context_block -> "## 記憶上下文\n..." (inject into the prompt)

# 3. Regenerate INDEX.md and every document's "## Related" block.
#    Idempotent: running twice produces identical files.
run_index_agent()
```

Each role is a versioned system prompt (`prompts/*.md`) + a restricted tool
set + a Pydantic output schema, running on `run_agent()` — see
[docs/modules/agents.md](docs/modules/agents.md) for details.

## Design Overview

- **Hand-written agent loop**, not the Hermes agent system — predictable and
  testable, no framework dependency.
- **JSON-string tool contract**: every tool returns `{"ok": true/false, ...}`
  in OpenAI function-calling format; tools never raise on user input.
- **Profile-safe memory directory**: resolved via
  `fabricium.state._get_global_hermes_home()` — never hardcodes `~/.hermes`.
- **Path traversal rejected**: `..`, absolute paths, NUL bytes, and symlink
  escapes all become error JSON.
- **Atomic writes only**: tmp file + `os.replace`; no partial files on crash.
- **Merge semantics live in the agent**: read first, supply the final
  complete merged content; the tool refuses to overwrite on `create`.

## Project Layout

```
src/tabularius/
├── llm.py          # OpenAI SDK wrapper → uniterra relay + retry
├── schemas.py      # Pydantic output contracts + parse_or_retry
├── tools.py        # Memory-dir tools (JSON-string contract)
├── prompts.py      # load_prompt + prompts/*.md (versioned system prompts)
├── agent_loop.py   # Generic tool-calling loop (run_agent)
├── prompts/        # Versioned role prompts (memory/recall/index/reader)
└── agents/         # Agent roles: memory / recall / index / reader
tests/              # Unit tests — real temp dirs, no network
docs/               # Architecture, conventions, module guides
```

## Development

```bash
uv run pytest tests/ -q   # full suite (no network)
uv run ruff check .       # lint
uv run mypy               # strict type check on src/tabularius
```

Prepend `unset PYTHONPATH` to every command when running under the Hermes
desktop (its PYTHONPATH shadows the project venv).

## Roadmap

- MemoryProvider integration (`on_session_end` / `prefetch`, issues #10–#11)
- `tabularius init` / `tabularius reindex` CLI (issue #12)
- `hermes memory setup` install flow (issue #14)

## License

MIT © Lai Tsz Kin
