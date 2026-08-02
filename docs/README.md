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

## Status

Phase 1 (foundation) implemented: repo scaffold, `llm.py`, `schemas.py`,
`tools.py`, `agent_loop.py`. Phase 2+ (agents, MemoryProvider integration,
CLI) are tracked as GitHub issues.
