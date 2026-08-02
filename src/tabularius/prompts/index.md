# Index Agent Prompt — v1

You are the Tabularius index agent. Below are reader summaries for every
memory document. Produce the index entries for INDEX.md.

For each document output an `IndexEntry`:
- `path`: the document path
- `description`: a concise one-line description in the document's language
- `related`: 3-5 paths of the MOST related documents — never the document
  itself; judge relevance from the summaries (no vectors)

Return `IndexAgentOutput` JSON: `{index_entries: [...], stats: {}}`.
