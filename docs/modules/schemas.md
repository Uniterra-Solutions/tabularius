# Module: schemas.py

Pydantic output contracts for all tabularius agents. Every agent returns
JSON; these models define the contract, and `model_validate_json`
performs parse + validation. `parse_or_retry` adds a `json_repair`
fallback for LLM output that is close to valid.

## Output Contracts

| Model | Fields | Used By |
|-------|--------|---------|
| `MemoryDocument` | `action: Literal["merge","create"]`, `path: str`, `content: str`, `reason: str` | memory agent (issue #7) |
| `MemoryAgentOutput` | `documents: list[MemoryDocument]`, `processed_sessions: list[str]`, `stats: dict[str, Any]` | memory agent |
| `RecallAgentOutput` | `context_block: str`, `documents_used: list[str]`, `relevance_notes: str` | recall agent (issue #8) |
| `ReaderAgentOutput` | `path: str`, `summary: str`, `key_topics: list[str]`, `category_hint: str` | reader agent (issue #9) |
| `IndexEntry` | `path: str`, `description: str`, `related: list[str] = []` | index agent (issue #9) |
| `IndexAgentOutput` | `index_entries: list[IndexEntry]`, `stats: dict[str, Any]` | index agent |

## parse_or_retry

```
parse_or_retry(content: str, schema: type[BaseModel]) -> BaseModel
```

1. `schema.model_validate_json(content)` — fast path.
2. On `ValidationError`, retry with `json_repair.loads(content)` then
   `schema.model_validate(repaired)`.
3. Either failure path raises `SchemaParseError(ValueError)` with the
   schema name and underlying error chained.

The agent loop catches `SchemaParseError` to retry with corrective
feedback.

## Notes

- `IndexEntry.related` defaults to `[]` — INDEX.md entries are
  `path + description`; related is optional.
- Pydantic v2 `model_validate` raises `ValidationError` (not `TypeError`)
  for non-dict repaired values (`"str"`, `123`, `true`) — all correctly
  become `SchemaParseError`.
