# Modules

Per-module deep dives for the phase-1 execution layer.

| Module | Doc | Responsibility |
|--------|-----|----------------|
| `llm.py` | [llm.md](llm.md) | OpenAI SDK wrapper → uniterra relay; JSON constraints; transient retry |
| `schemas.py` | [schemas.md](schemas.md) | Pydantic output contracts; `parse_or_retry` |
| `tools.py` | [tools.md](tools.md) | Memory-dir tools; JSON-string contract; path safety |
| `agent_loop.py` | [agent_loop.md](agent_loop.md) | Generic tool-calling loop (`run_agent`) |
