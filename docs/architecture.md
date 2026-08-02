# Architecture

## System Context

Tabularius is a Hermes MemoryProvider plugin. It extracts conversation
memory from session transcripts, stores it as markdown files in a
profile-safe memory directory, and injects relevant context back into
prompts.

```
Hermes (trigger layer)
   │  on_session_end(messages) / prefetch(query)   [phase 2+]
   ▼
MemoryProvider (fabricium integration, phase 3)
   │
   ▼
Agent layer (phase 2+: memory / recall / index / reader agents)
   │
   ▼
Execution layer (phase 1 — THIS DOCUMENT)
   ├── llm.py         OpenAI SDK wrapper → uniterra relay
   ├── schemas.py     Pydantic output contracts + parse_or_retry
   ├── tools.py       Hand-written memory tools (JSON-string contract)
   └── agent_loop.py  Generic tool-calling loop (run_agent)
```

Phase 1 delivers the execution layer only. The agent roles, provider
integration, and CLI are later phases built on top of these primitives.

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `llm.py` | Resolve API key (`TABULARIUS_API_KEY` → `OPENAI_API_KEY`); wrap OpenAI chat-completions against the uniterra relay; enforce `response_format=json_object` + JSON-only system suffix; retry 429/5xx/timeout with exponential backoff |
| `schemas.py` | Define every agent output contract as a Pydantic model; `parse_or_retry()` parses LLM JSON with a `json_repair` fallback and raises `SchemaParseError` on unfixable content |
| `tools.py` | Hand-written tools over the memory directory: `memory_read`, `memory_write` (create/merge), `memory_list`, `index_update`, `spawn_reader`. All return JSON strings; path traversal rejected; writes atomic |
| `agent_loop.py` | `run_agent()` drives an LLM through JSON + optional tool calls until it returns schema-valid JSON. Tool dispatch via `TOOL_REGISTRY` (role-configurable); schema violations retry with corrective feedback |

## Data Flow

### Write path (memory agent, phase 2+)

```
transcript batch → memory agent (run_agent)
  → MemoryAgentOutput {documents: [{action, path, content, reason}]}
  → tools.memory_write(path, content, action)
      create: file must NOT exist (refuses overwrite)
      merge:  file must exist; agent supplies final complete content
  → atomic tmp + os.replace into ~/.hermes/memory/
```

### Read path (recall agent, phase 2+)

```
query → recall agent (run_agent)
  → tools.memory_list()     (INDEX.md entries: path + description)
  → tools.memory_read(path) (candidate documents, ≤3)
  → RecallAgentOutput {context_block, documents_used, relevance_notes}
  → context_block injected into prompt
```

### Index path (index agent, phase 2+)

```
memory_list → spawn_reader(path) per doc → ReaderAgentOutput
  → classify + build entries → tools.index_update(entries)
  → INDEX.md regenerated atomically
```

## Key Decisions

1. **Own agent loop, not Hermes agents.** Each role is a prompt + tool set
   + schema running on `run_agent()`. Predictable, testable, no framework
   dependency. (issue #6)
2. **Tools return JSON strings.** OpenAI function-calling requires string
   tool results. Uniform `{"ok": true/false}` envelope; tools never raise
   on user input. (issue #5)
3. **fabricium for home resolution.** `_get_global_hermes_home()` resolves
   the real `~/.hermes/` even when `HERMES_HOME` points at a profile
   subdirectory. (issue #5)
4. **json_object + tools both supported.** The relay (uniterra +
   deepseek-v4-flash) accepts `response_format=json_object` with and
   without tools; verified in issue #3 acceptance.
5. **Merge semantics live in the agent, not the tool.** The agent reads the
   existing file first and supplies the final complete content; the tool
   only writes atomically and refuses to overwrite on `create`.
