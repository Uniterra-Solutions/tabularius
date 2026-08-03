# Modules

Per-module deep dives for the execution layer and agent roles.

| Module | Doc | Responsibility |
|--------|-----|----------------|
| `llm.py` | [llm.md](llm.md) | OpenAI SDK wrapper → uniterra relay; JSON constraints; transient retry |
| `schemas.py` | [schemas.md](schemas.md) | Pydantic output contracts; `parse_or_retry` |
| `tools.py` | [tools.md](tools.md) | Memory-dir tools; JSON-string contract; path safety |
| `prompts.py` | [agents.md](agents.md#prompts) | Versioned role prompts (`prompts/*.md`) |
| `agent_loop.py` | [agent_loop.md](agent_loop.md) | Generic tool-calling loop (`run_agent`) |
| `agents/` | [agents.md](agents.md) | memory / recall / index / reader roles (issues #7–#9) |
