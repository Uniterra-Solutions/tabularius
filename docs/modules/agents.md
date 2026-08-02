# Module: agents/

Tabularius agent roles (memory / recall / index / reader). Every role is a
versioned system prompt (`src/tabularius/prompts/`) + tool set + output
schema running on the shared `run_agent` loop. Entry points are exported
from `tabularius.agents`.

| Role | Entry point | Trigger | Output |
|------|-------------|---------|--------|
| memory | `run_memory_agent(transcripts)` | `on_session_end` (Hermes integration) | `MemoryAgentOutput` |
| recall | `run_recall_agent(query, session=...)` | `prefetch(query)` (before every LLM call) | `RecallAgentOutput` |
| index | `run_index_agent()` | `tabularius init` / `tabularius reindex` (CLI, issue #12) | `IndexAgentOutput` |
| reader | `run_reader(path)` | index agent / `tools.spawn_reader` | `ReaderAgentOutput` |

## Memory agent (#7)

Input is a batch of session transcripts (typically 5). The agent classifies
information into topic files (`uniterra-vps-infra.md`, `uniterra-email.md`,
...): new information merges into an existing topic file, and a new file is
created only when no existing file covers the topic.

**Merge semantics live in the agent, not the tool.** The prompt requires
`memory_read` before writing; updates pass the FINAL COMPLETE merged
content with `action="merge"`, and `action="create"` refuses to overwrite.
The tool set exposed to the model is restricted to `memory_read` +
`memory_write` (`MEMORY_TOOLS`).

## Recall agent (#8)

Flow: read INDEX.md (small) → LLM picks ≤3 candidate documents not already
loaded → `memory_read` each → concise `context_block` (~300 tokens)
starting with `## 記憶上下文`. Cost control is per-session via
`RecallSession`:

- **First call**: INDEX.md entries + the 2-3 most-used documents
  (`preload_paths`, chosen by the integration layer; falls back to the
  first INDEX.md entries). Preloaded contents are placed in the prompt.
- **Later calls**: only INDEX.md filtering; documents already read are
  listed as "already loaded" and never re-read. Every successful
  `memory_read` is recorded into the session's `_session_prefetched` cache
  by a tracking dispatch.
- **Timeout**: default 5 s (`RECALL_TIMEOUT`); on `APITimeoutError` the
  agent returns an empty `context_block` instead of raising, so recall
  never blocks the conversation.

## Index agent (#9)

```
list docs (sorted, excludes INDEX.md)
→ spawn_reader per doc (keeps index-agent context small)
→ one LLM call: classify + judge relatedness from summaries (zero vectors)
→ index_update(entries)  → INDEX.md
→ append "## Related" block (3-5 entries) to every document (atomic)
```

- `_build_entries` normalizes LLM output: hallucinated paths are dropped,
  `related` is capped at 5 and excludes self, and documents the LLM missed
  are filled from their reader summary — every scanned document appears in
  INDEX.md.
- Reindex is deterministic given the same reader/classification outputs:
  the document scan is sorted, INDEX.md renders in that order, and the
  Related block is strip-and-appended atomically (running twice yields
  identical files; LLM variance aside).

## Reader agent (#9)

One document → `ReaderAgentOutput` (summary + key_topics + category_hint).
`tools.spawn_reader` is a thin JSON wrapper over `run_reader`; path safety
and missing-file errors surface as `ToolError` (→ error JSON at the tool
boundary).

## Prompts

`prompts.py` exposes `PROMPTS_DIR` + `load_prompt(name)`. Prompts live in
`src/tabularius/prompts/*.md` (one file per role), each with a version
marker in its header (`— v1`). Bump the version whenever the behaviour of
a prompt changes; prompts are plain markdown so they are diffable and
reviewable outside code.
