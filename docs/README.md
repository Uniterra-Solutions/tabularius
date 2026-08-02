# Documentation

Tabularius — Hermes MemoryProvider plugin: extract, index, and recall
conversation memory as markdown.

## Index

| Document | Purpose |
|---|---|
| [architecture.md](architecture.md) | System context, module responsibilities, data flow |
| [conventions.md](conventions.md) | Naming, imports, types, error handling, security |
| [project-structure.md](project-structure.md) | Directory tree, responsibility table |
| [tech-stack.md](tech-stack.md) | Version table, runtime deps rationale, external services |
| [testing.md](testing.md) | Test commands, fixture patterns, mock policy |
| [modules/overview.md](modules/overview.md) | Per-module deep dives index |
| [modules/agents.md](modules/agents.md) | Agent roles: memory / recall / index / reader |

## Status

Phase 1 (foundation) implemented: repo scaffold, `llm.py`, `schemas.py`,
`tools.py`, `agent_loop.py`. Phase 2 (agent roles, issues #7–#9)
implemented in `agents/` with versioned prompts in `prompts/`. Remaining:
MemoryProvider integration (issues #10–#11), CLI (issue #12), tests
(issue #13), docs (issue #14).
