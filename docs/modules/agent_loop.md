# Module: agent_loop.py

Generic tool-calling agent loop shared by all tabularius agents. Not the
Hermes agent system — a purpose-built loop that drives an LLM through
JSON outputs and optional tool calls until it produces a schema-valid
answer. Every agent role (memory / recall / index / reader) runs on this
loop with its own system prompt, tool set, and output schema.

## Public API

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `run_agent(system, user, tools, schema, *, client=None, dispatch=None, timeout=None, max_schema_retries=2, max_tool_rounds=25)` | `-> BaseModel` | The loop |
| `MAX_SCHEMA_RETRIES` | `int` | `2` |
| `MAX_TOOL_ROUNDS` | `int` | `25` |
| `_default_dispatch(name, args)` | `(str, dict) -> str` | Looks up `TOOL_REGISTRY` |

## Loop Semantics

```
messages = [system, user]
for _ in range(max_tool_rounds + 1):
    response = llm.chat(messages, tools, json_object)
    if response.choices empty → RuntimeError("...no choices")
    if message.tool_calls:
        # OpenAI rule: echo assistant tool_call message BEFORE tool results
        messages.append(message.model_dump(exclude_none=True))
        for call in tool_calls:
            args = json.loads(call.function.arguments or "{}")
            result = dispatch(name, args)     # wrapped in except Exception → error JSON
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
        continue
    return parse_or_retry(message.content or "", schema)
    # on SchemaParseError: retry up to max_schema_retries, appending
    # corrective feedback as a user message
raise RuntimeError("agent loop exceeded <n> tool rounds")
```

## Key Rules

- **Assistant tool_call message echo**: required by OpenAI — tool result
  messages must follow the assistant message containing the matching
  `tool_call_id`.
- **Schema violation retry**: on `SchemaParseError`, appends a user
  message with the parse error and asks the model to fix it. Max 2
  retries, then re-raise.
- **Tool dispatch**: `dispatch` defaults to `_default_dispatch` →
  `TOOL_REGISTRY` lookup. Roles can inject a custom dispatch for a
  restricted tool set. Unknown tool → error JSON fed back to model.
- **Raising tools**: dispatch is wrapped in `except Exception` so a
  tool that raises feeds `{"ok": false, "error": "<name>: <exc>"}` back
  to the model instead of crashing the run.
- **Tool round limit**: `max_tool_rounds + 1` iterations (25 tool rounds
  + final answer), then `RuntimeError`.
- **`client` injectable** for tests; default `LLMClient()` reads the env
  key. `timeout` passes through to each `llm.chat` call.
