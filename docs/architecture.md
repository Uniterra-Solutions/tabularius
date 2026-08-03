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
2, issues #7–#9) run on top of these primitives. Phase 3 (issues #10–#12)
adds the MemoryProvider integration (`provider.py`), profile-safe state
(`state.py`), and the CLI (`cli.py`, `sessions.py`).

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `llm.py` | Resolve API key (`TABULARIUS_API_KEY` → `OPENAI_API_KEY`); wrap OpenAI chat-completions against the uniterra relay; enforce `response_format=json_object` + JSON-only system suffix; retry 429/5xx/timeout with exponential backoff |
| `schemas.py` | Define every agent output contract as a Pydantic model; `parse_or_retry()` parses LLM JSON with a `json_repair` fallback and raises `SchemaParseError` on unfixable content |
| `tools.py` | Hand-written tools over the memory directory: `memory_read`, `memory_write` (create/merge), `memory_list`, `index_update`, `spawn_reader`. All return JSON strings; path traversal rejected; writes atomic |
| `prompts.py` | `load_prompt(name)` + `PROMPTS_DIR` — versioned system prompts (`prompts/*.md`) for every agent role |
| `agents/` | Role implementations: `memory.py` (extract→merge-write), `recall.py` (query→context block, session cache), `index.py` (INDEX.md + Related), `reader.py` (doc→summary). All run on `run_agent` |
| `agent_loop.py` | `run_agent()` drives an LLM through JSON + optional tool calls until it returns schema-valid JSON. Tool dispatch via `TOOL_REGISTRY` (role-configurable); schema violations retry with corrective feedback |
| `provider.py` | `TabulariusMemoryProvider` (issue #10): `on_session_end` → daemon extraction, `prefetch`/`queue_prefetch` → recall context, `on_memory_write` → mirror (add only), `shutdown`/atexit → drain. Concurrency: daemon writer tracking, atomic snapshots, idempotent commits |
| `state.py` | `tabularius_state.json` (issue #11): `committed_sessions` (cross-process idempotency), `last_reindex`, `extraction_stats`. Profile-safe via fabricium `_get_global_hermes_home()` |
| `sessions.py` | state.db scanning (issue #12): read-only, schema tolerant; `find_unprocessed` merges committed + legacy archive |
| `cli.py` | `hermes tabularius status/setup/update/init/reindex` (issues #11–#12) via the memory-plugin `register_cli` convention |

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

### Provider path (issue #10)

```
on_session_end(messages) → snapshot (lock) → daemon thread
  → idempotency check (committed_sessions) → run_memory_agent([transcript])
  → memory_write per doc (atomic) → record_extraction (state.json)
prefetch(query) → recall agent (5s timeout, empty on failure) → context block
on_memory_write(action=="add") → mirror to agent-notes.md / user-profile.md
shutdown / atexit → _drain_writers (timeout-bounded, never hangs)
```

Concurrency safety (OpenViking lessons): a daemon writer thread tracked in
`_inflight_writers` keyed by session id; `_session_state_lock` makes
session snapshots atomic so concurrent `sync_turn` calls never lose a
turn; commits are idempotent and persisted cross-process in
`tabularius_state.json` (a Hermes restart never re-extracts); atexit drains
in-flight writers as a safety net.

### Init / reindex path (issues #11–#12)

```
tabularius init (dry-run default) → scan state.db (read-only, tolerant)
  → diff against committed_sessions (+ legacy archive) → report
tabularius init --force → backup MEMORY.md/USER.md → archive/pre-init-<ts>.json
  → batches of 5 → memory agent → merge-write .md → record commits
  → index agent (INDEX.md + Related) → record_reindex
  → clear MEMORY.md (→ INDEX.md pointer), USER.md untouched
tabularius reindex → index agent only (idempotent)
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
7. **Extraction is real-time and non-blocking.** `on_session_end` spawns a
   daemon thread; it never blocks the session teardown, and it never waits
   for a batch (`tabularius init` handles history). Idempotency is
   cross-process: `committed_sessions` lives in `tabularius_state.json`,
   so a Hermes restart does not re-extract (issue #10).
8. **CLI follows the memory-provider convention.** `cli.py` exposes
   `register_cli(subparser)` + `tabularius_command`, discovered by Hermes
   only when `memory.provider: tabularius` is active. `setup/status/update`
   reuse fabricium's `HermesPlugin` lifecycle; `init/reindex` are the batch
   commands (issues #11–#12).
9. **state.db is scanned read-only and schema-tolerantly.** `tabularius
   init` never opens the Hermes session store for writing; missing
   tables/columns degrade to empty results, and the legacy
   `archive/processed-sessions.json` record is merged so already-processed
   sessions are not re-extracted (issue #12).
