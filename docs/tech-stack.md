# Tech Stack

## Version Table

| Tool | Version | Purpose |
|------|---------|---------|
| Python | ≥ 3.10 (floor) | Language |
| uv | 0.9+ | Package manager / venv / lockfile |
| hatchling | build backend | src-layout wheel builds |
| openai | ≥ 1.0 (installed 2.24) | Chat-completions SDK → uniterra relay |
| pydantic | ≥ 2 (installed 2.13) | Output contract validation |
| httpx | ≥ 0.27 | HTTP transport (openai SDK dep) |
| json-repair | ≥ 0.20 (installed 0.61) | LLM JSON parse fallback |
| fabricium | ≥ 0.3.0 | `_get_global_hermes_home()` profile-safe resolution |
| pytest | ≥ 8 (installed 9.1) | Tests |
| ruff | ≥ 0.8 (installed 0.16) | Lint (E, F, I, N, W) + format |
| mypy | ≥ 1.16 (installed 2.3) | Strict type check on `src/tabularius` |

## Runtime Deps Rationale

| Dep | Why |
|-----|-----|
| openai | Direct OpenAI SDK wrapper; the relay exposes an OpenAI-compatible `/v1` |
| pydantic | `model_validate_json` gives parse + validation in one step for agent JSON output |
| httpx | Comes with the openai SDK; pinned explicitly per issue #2 |
| json-repair | LLMs occasionally emit near-valid JSON (unquoted keys, trailing commas); repair before failing |
| fabricium | Uniterra's shared plugin infrastructure; provides `_get_global_hermes_home()` for profile-safe `~/.hermes` resolution |

## External Services

| Service | Endpoint | Used For |
|---------|----------|----------|
| Uniterra relay | `https://api.uniterra-solutions.com/v1` | All LLM calls (`deepseek-v4-flash`) |

No other external services. Unit tests make zero network calls. The Docker
E2E suite (`tests/e2e/`) additionally depends on Docker + the
`nousresearch/hermes-agent:latest` image (pulled at build time via
`Dockerfile.test`); it is skipped automatically when either is missing.

## Config Surface

| Env Var | Purpose |
|---------|---------|
| `TABULARIUS_API_KEY` | Relay API key (preferred) |
| `OPENAI_API_KEY` | Fallback API key |
| `HERMES_HOME` | Hermes home override (via fabricium resolution) |
