# Module: tools.py

Hand-written tools for tabularius agents. All tools operate on the
profile-safe memory directory (`~/.hermes/memory/`, resolved via
fabricium's `_get_global_hermes_home()`). Every tool returns a JSON
string in OpenAI function-calling format.

## Public API

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `memory_dir()` | `() -> Path` | Profile-safe memory directory |
| `memory_read(path)` | `(str) -> str` | Read one .md file; content or explicit error |
| `memory_write(path, content, action)` | `(str, str, str) -> str` | Create/merge with overwrite protection; atomic |
| `memory_list()` | `() -> str` | INDEX.md entries (path + description) |
| `index_update(entries)` | `(list[dict]) -> str` | Regenerate INDEX.md atomically |
| `spawn_reader(path, *, client=None)` | `(str, LLMClient\|None) -> str` | Reader agent over one document → `ReaderAgentOutput` |
| `TOOL_SCHEMAS` | `list[dict]` | OpenAI function-calling schemas for all tools |
| `TOOL_REGISTRY` | `dict[str, Callable]` | name → tool callable (agent loop dispatch) |

## Tool JSON Contract

```
{"ok": true, ...}    success
{"ok": false, "error": "..."}    failure
```

`ensure_ascii=False` — Chinese/markdown content round-trips unescaped.

## Tool Semantics

### memory_read(path)
- Missing file → `{"ok": false, "error": "file not found: <path>"}`
- Unsafe path → `{"ok": false, "error": "path escapes memory directory: ..."}`
- Success → `{"ok": true, "path": ..., "content": ...}`

### memory_write(path, content, action)
- `action="create"` — file must NOT exist; refuses overwrite
  (`"refusing to overwrite existing file"`).
- `action="merge"` — file must exist; agent must have read the current
  file first and supply the FINAL complete content. The tool only writes
  atomically; it never merges text itself.
- Unwritable target (dir target, file parent, permission, disk full) →
  `{"ok": false, "error": "write failed: ..."}`.

### memory_list()
- No INDEX.md → `{"ok": true, "entries": []}`
- Parses the `## Categories` section: `- \`path.md\` — description`.

### index_update(entries)
- Validates each entry as `IndexEntry`, renders canonical INDEX.md
  (`# Memory Index` + auto-generated comment + `## Categories`), writes
  atomically. Returns `{"ok": true, "count": N}`.

### spawn_reader(path, *, client=None)
- Reads the document, runs the reader agent via `run_agent` (lazy import
  to avoid a module-level cycle), returns `ReaderAgentOutput` JSON.
- `client` injectable for tests.

## Security

- `_resolve_path()`: resolve + `is_relative_to(memory_root)` rejects
  `..`, absolute paths, NUL bytes (`ValueError` → `ToolError`), and
  symlink loops (`OSError` → `ToolError`).
- Writes are atomic: `tempfile.mkstemp` + `os.replace`, cleanup on error.
