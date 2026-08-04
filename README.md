# Tabularius

Hermes MemoryProvider plugin: automatically extracts, indexes, and recalls
conversation memory as markdown.

Tabularius turns session transcripts into durable, topic-classified markdown
files in a profile-safe memory directory, and injects the relevant context
back into prompts before each LLM call.

## Status

- **Implemented**: phase-1 execution layer (LLM client, output schemas,
  memory tools, generic agent loop), phase-2 agent roles (memory / recall /
  index / reader), and phase-3 Hermes integration: the `MemoryProvider`
  (`on_session_end` real-time extraction, `prefetch` recall, memory
  mirror), profile-safe state, and the `tabularius init` / `reindex` /
  `status` CLI (issues #10–#12).

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

## Install as a Hermes memory provider

Hermes discovers user memory providers as **directories** under
`~/.hermes/plugins/<name>/` (not pip entry points). After installing the
package into Hermes' Python environment, create a thin shim directory that
re-exports the package:

```bash
# 1. Install the package (into the Hermes venv when using `hermes`)
pip install tabularius

# 2. Shim directory — Hermes' memory-provider discovery scans
#    ~/.hermes/plugins/<name>/ for __init__.py + cli.py
mkdir -p ~/.hermes/plugins/tabularius
cat > ~/.hermes/plugins/tabularius/__init__.py <<'EOF'
from tabularius import register  # noqa: F401
from tabularius.provider import TabulariusMemoryProvider  # noqa: F401 (MemoryProvider marker)
EOF
cat > ~/.hermes/plugins/tabularius/cli.py <<'EOF'
from tabularius.cli import register_cli, tabularius_command  # noqa: F401
EOF

# 3. Activate — the `hermes tabularius ...` CLI appears once active
hermes config set memory.provider tabularius

# 4. Migrate history (extract all unprocessed sessions, build the index,
#    back up memory entries, switch MEMORY.md to the INDEX.md pointer)
hermes tabularius init --force

# 5. Check status
hermes tabularius status
```

`hermes tabularius setup` performs the same activation (step 3) plus
ensures the memory directory exists.

## Configuration

| Env var | Purpose |
|---------|---------|
| `TABULARIUS_API_KEY` | Relay API key (preferred) |
| `OPENAI_API_KEY` | Fallback API key |
| `TABULARIUS_BASE_URL` | Relay base URL (default: `https://api.uniterra-solutions.com/v1`) |
| `TABULARIUS_MODEL` | Relay model (default: `deepseek-v4-flash`) |
| `TABULARIUS_MAX_TOKENS` | Max output tokens per LLM call (default: `2000`; auto-doubled up to `32000` when a response is truncated) |
| `TABULARIUS_TIMEOUT` | Request timeout in seconds (default: `60.0`) |
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
├── __init__.py     # register(ctx) → MemoryProvider (Hermes plugin entry)
├── plugin.yaml     # Hermes plugin manifest
├── provider.py     # MemoryProvider: on_session_end / prefetch / mirror
├── state.py        # tabularius_state.json (committed_sessions, stats)
├── sessions.py     # state.db scanning (read-only, schema tolerant)
├── cli.py          # hermes tabularius status/setup/update/init/reindex
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

## CLI

As a Hermes memory provider, the CLI is discovered when
`memory.provider: tabularius` is active (`hermes memory setup`, or
`hermes config set memory.provider tabularius`):

```bash
hermes tabularius status          # provider + extraction state
hermes tabularius init            # dry run: report unprocessed sessions
hermes tabularius init --force    # migrate: extract all + index + switch MEMORY.md
hermes tabularius reindex         # rebuild INDEX.md + Related only
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

- Follow-up hardening from review: provider double-trigger guard, bounded
  prefetch caches, stale queued recall (issues #15–#17)

## License

MIT © Lai Tsz Kin
