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
Agent layer (phase 2: agents/ — memory / recall / index / reader roles)
   │
   ▼
Execution layer (phase 1)
   ├── llm.py         OpenAI SDK wrapper → uniterra relay
   ├── schemas.py     Pydantic output contracts + parse_or_retry
   ├── tools.py       Hand-written memory tools (JSON-string contract)
   ├── prompts.py     Versioned system prompts (prompts/*.md)
   └── agent_loop.py  Generic tool-calling loop (run_agent)
```

Phase 1 delivers the execution layer; the agent roles in `agents/` (phase
2, issues #7–#9) run on top of these primitives. The MemoryProvider
integration and CLI are later phases.

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `llm.py` | Resolve API key (`TABULARIUS_API_KEY` → `OPENAI_API_KEY`); wrap OpenAI chat-completions against the uniterra relay; enforce `response_format=json_object` + JSON-only system suffix; retry 429/5xx/timeout with exponential backoff |
| `schemas.py` | Define every agent output contract as a Pydantic model; `parse_or_retry()` parses LLM JSON with a `json_repair` fallback and raises `SchemaParseError` on unfixable content |
| `tools.py` | Hand-written tools over the memory directory: `memory_read`, `memory_write` (create/merge), `memory_list`, `index_update`, `spawn_reader`. All return JSON strings; path traversal rejected; writes atomic |
| `prompts.py` | `load_prompt(name)` + `PROMPTS_DIR` — versioned system prompts (`prompts/*.md`) for every agent role |
| `agents/` | Role implementations: `memory.py` (extract→merge-write), `recall.py` (query→context block, session cache), `index.py` (INDEX.md + Related), `reader.py` (doc→summary). All run on `run_agent` |
| `agent_loop.py` | `run_agent()` drives an LLM through JSON + optional tool calls until it returns schema-valid JSON. Tool dispatch via `TOOL_REGISTRY` (role-configurable); schema violations retry with corrective feedback |

## Data Flow

### Write path (memory agent, issue #7)

```
transcript batch → run_memory_agent (prompts/memory.md, tools: memory_read/write)
  → MemoryAgentOutput {documents: [{action, path, content, reason}]}
  → tools.memory_write(path, content, action)
      create: file must NOT exist (refuses overwrite)
      merge:  file must exist; agent supplies final complete content
  → atomic tmp + os.replace into ~/.hermes/memory/
```

### Read path (recall agent, issue #8)

```
query → run_recall_agent (prompts/recall.md, tools: memory_read)
  → memory_list()      (INDEX.md entries: path + description)
  → memory_read(path)  (candidate documents, ≤3, none already loaded)
  → RecallAgentOutput {context_block, documents_used, relevance_notes}
  → context_block injected into prompt (## 記憶上下文)
Cost control: first call preloads the 2-3 most-used documents; a
RecallSession cache prevents re-reading; a 5s timeout returns an empty
context instead of blocking.
```

### Index path (index agent, issue #9)

```
sorted doc scan (excludes INDEX.md) → run_reader(path) per doc → ReaderAgentOutput
  → one LLM call: classify + relatedness from summaries (zero vectors)
  → tools.index_update(entries)          → INDEX.md regenerated atomically
  → strip-and-append "## Related" (3-5)  → every document, atomic merge
Reindex is idempotent: sorted scan + stable rendering + atomic replace.
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
6. **Prompts versioned outside code; orchestration deterministic.** Prompts
   live in `prompts/*.md` with version markers (`— v1`) so behaviour changes
   are reviewable diffs. The index agent confines LLM judgment to
   classification + relatedness and keeps the rest (sorted scan,
   strip-and-append of `## Related`, INDEX.md rendering) deterministic, so
   reindex is idempotent.
