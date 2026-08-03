# Tabularius

## Build & Test

```bash
# Install dev deps (once)
uv sync --dev

# Full test suite (unit + Docker E2E; e2e skips without docker)
uv run pytest tests/ -q

# Just the Docker E2E layer (tests/e2e/)
uv run pytest tests/e2e/ -q

# Single test file
uv run pytest tests/test_tools.py -q

# Lint
uv run ruff check .

# Format check / apply
uv run ruff format --check .
uv run ruff format .

# Type check
uv run mypy
```

Run `uv sync --dev` once after cloning to install dev dependencies into `.venv/`.
Prepend `unset PYTHONPATH` to every command if you run under the Hermes desktop
(its PYTHONPATH shadows the project venv).

## Tech Stack

- **Language**: Python ≥ 3.10 (target 3.10 floor)
- **Package manager**: `uv` — lockfile at `uv.lock`
- **Build system**: hatchling (`pyproject.toml`, src layout)
- **Testing**: pytest ≥ 8 (151 tests: 138 unit + 13 Docker E2E, `tests/` directory)
- **Lint/Format**: ruff ≥ 0.8 (rules E, F, I, N, W; line-length 100)
- **Type check**: mypy ≥ 1.16 (`--strict` mode on `src/tabularius`)
- **Runtime deps**: openai, pydantic ≥ 2, httpx, json-repair, fabricium

## Project Structure

| Directory | Responsibility |
|---|---|
| `src/tabularius/` | Core library: LLM client, output schemas, tools, agent loop |
| `src/tabularius/prompts/` | Versioned system prompts per role (`prompts.py` loader) |
| `src/tabularius/agents/` | Agent roles: memory / recall / index / reader (phase 2) — see `docs/modules/agents.md` |
| `src/tabularius/` (phase 3) | `provider.py` MemoryProvider + concurrency, `state.py` state.json, `sessions.py` state.db scan, `cli.py` init/reindex/status — see `docs/modules/provider.md` |
| `tests/` | Unit tests — real temp dirs, no network |
| `tests/e2e/` | Docker E2E — plugin inside `nousresearch/hermes-agent` (see `docs/testing.md`); skipped without docker |
| `Dockerfile.test` | Derived test image (build-time deps; `/opt/hermes` immutable at runtime) |
| `docs/` | Architecture, conventions, testing guides — not task instructions |

## Key Constraints

- **Every tool returns a JSON string** (`{"ok": true/false, ...}`) in OpenAI
  function-calling format. Tools never raise on user input — path errors,
  missing files, and write failures are translated to error JSON.
- **Memory directory is profile-safe.** Resolved via
  `fabricium.state._get_global_hermes_home() / "memory"` — never hardcode
  `~/.hermes`.
- **Path traversal is rejected.** `_resolve_path()` resolves and checks
  `is_relative_to(memory_root)`; `..`, absolute paths, NUL bytes, and
  symlink escapes all become `ToolError`.
- **Atomic writes only.** All memory file writes go through tmp + `os.replace`.
- **No hardcoded secrets.** API key from `TABULARIUS_API_KEY` →
  `OPENAI_API_KEY` fallback.
- **Agent loop is hand-written** — not the Hermes agent system. Every role
  runs on `run_agent()` with its own system prompt, tool set, and output
  schema.

## Git Workflow

- **Conventional Commits**: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`,
  `chore:`.
- **Stacked PRs**: phase commits build on each other; each PR targets the
  previous phase branch, top of stack targets `main`.
- **Release tags**: `v<version>` (e.g. `v0.1.0`).

## Boundaries

**Always:**
- Run tests before committing (`uv run pytest tests/ -q`)
- Add tests for new code
- Match existing conventions in `docs/conventions.md`

**Ask first:**
- Adding a runtime dependency
- Changing the output schema contract (`docs/modules/schemas.md`)
- Modifying the tool JSON contract (`docs/modules/tools.md`)
- Bumping the Python version floor

**Never:**
- Commit `.env` files or secrets
- Use relative imports inside `src/tabularius/`
- Let a tool raise on malformed input — return error JSON instead
