# Module: provider / state / sessions / cli

Phase-3 integration surface (issues #10–#12): the Hermes MemoryProvider
plugin wiring, profile-safe state, state.db scanning, and CLI commands.

## provider.py — `TabulariusMemoryProvider` (#10)

Subclasses `agent.memory_provider.MemoryProvider` when running inside
Hermes; degrades to a plain object with the same surface when imported
standalone (unit tests, packaging) via a `TYPE_CHECKING` import. The
Hermes-only ABC is stubbed for mypy in `stubs/agent/memory_provider.pyi`
(mypy_path configured in pyproject.toml).

| Hook | Behaviour |
|------|-----------|
| `initialize(session_id, **kwargs)` | Stores session identity; registers the atexit safety net |
| `sync_turn(user, asst)` | Buffers the turn under `_session_state_lock` (cheap, in-memory) |
| `on_session_end(messages)` | Snapshot transcript atomically → spawn **daemon** extraction thread (non-blocking) → memory agent → merge-write .md → `record_extraction` (idempotent) |
| `prefetch(query)` | Recall agent, 5s timeout, empty string on any failure; consumes a `queue_prefetch`-warmed result when present |
| `queue_prefetch(query)` | Warm the next turn's recall on a daemon thread |
| `on_memory_write(action, target, content)` | Mirrors `action == "add"` only → `agent-notes.md` (target=memory) / `user-profile.md` (target=user), exact-duplicate deduped, no agent call |
| `get_tool_schemas()` | `memory_read` / `memory_write` / `memory_list` (internal tools stay out of the conversation toolset) |
| `handle_tool_call(name, args)` | Dispatches advertised tools via `TOOL_REGISTRY`; unknown → error JSON |
| `shutdown()` | Sets `_shutting_down`, drains all writers (timeout-bounded) |
| `backup_paths()` | Memory dir + `tabularius_state.json` for `hermes backup` |

### Concurrency (OpenViking lessons)

- **Daemon writer tracking** — `_spawn_writer(sid, target, name)` keeps a
  set of threads per session id in `_inflight_writers`; each writer removes
  itself in `finally`.
- **`_drain_writers(sid, timeout)`** — joins in-flight writers within a
  shared deadline; returns False (caller skips) instead of hanging.
- **Drain timeout fits the Hermes exit watchdog** — `SESSION_DRAIN_TIMEOUT`
  (25s) stays under Hermes' CLI `HERMES_EXIT_WATCHDOG_S` default (30s):
  a real extraction is an LLM-bound round-trip (15-25s for long
  transcripts), and a shorter drain let the daemon writer die with the
  interpreter, silently skipping the commit (Docker QA 2026-08).
- **`_session_state_lock`** — atomic snapshots of session id + buffered
  turns so concurrent `sync_turn` calls never lose a turn.
- **Idempotent commit** — `committed_sessions` in `tabularius_state.json`
  is cross-process: a Hermes restart never re-extracts. Partial write
  failures leave the session uncommitted so `init` retries it.
- **atexit safety net** — `_atexit_commit_pending` drains in-flight
  writers at process exit; sessions not yet started are recovered by
  `tabularius init` (cross-process scan).

## state.py — `tabularius_state.json` (#11)

Profile-safe persistence at `_get_global_hermes_home() / "tabularius_state.json"`:

```json
{
  "committed_sessions": {"<session_id>": "<iso timestamp>"},
  "last_reindex": "<iso timestamp>" | null,
  "extraction_stats": {"<session_id>": {"docs": n, "sessions": n, "at": "..."}}
}
```

Writes are atomic (tmp + `os.replace`) and serialized by a module lock so
concurrent daemon writers never corrupt the file. `legacy_processed_sessions`
reads the pre-state.json `memory/archive/processed-sessions.json` record so
already-processed sessions from the pilot phase are not re-extracted.

## sessions.py — state.db scanning (#12)

Read-only (`?mode=ro`) and schema-tolerant: missing files, tables, or
columns degrade to empty results. `scan_sessions` lists sessions with at
least one message (oldest first); `find_unprocessed` diffs against the
committed record; `load_transcript` renders one session's messages as
`## role` blocks.

## cli.py — `hermes tabularius <...>` (#11–#12)

Follows the Hermes memory-provider CLI convention
(`plugins.memory.discover_plugin_cli_commands`): `register_cli(subparser)`
builds the argparse tree and `tabularius_command` dispatches. Discovery is
gated on `memory.provider: tabularius` in config.yaml.

| Command | Behaviour |
|---------|-----------|
| `status` | Provider availability + committed count + last extraction/reindex |
| `setup` | Ensure memory dir; activate via `hermes config set memory.provider tabularius` |
| `update [--check]` | Fabricium self-update (pip preferred, git fallback) |
| `init [--force] [--db PATH]` | **Dry-run by default**: report unprocessed sessions + what would run. `--force`: backup entries → batches of 5 → memory agent → merge-write → index agent → record state → clear MEMORY.md (→ INDEX.md pointer), USER.md untouched |
| `reindex` | Index agent only (idempotent) |
