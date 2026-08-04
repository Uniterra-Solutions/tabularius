# Module: llm.py

OpenAI SDK wrapper pointed at the uniterra relay. Handles API key
resolution, JSON output constraints, and transient-error retry for every
tabularius agent call.

## Public API

| Symbol | Signature | Notes |
|--------|-----------|-------|
| `DEFAULT_BASE_URL` | `str` | `https://api.uniterra-solutions.com/v1` |
| `DEFAULT_MODEL` | `str` | `deepseek-v4-flash` |
| `DEFAULT_MAX_TOKENS` | `int` | `2000` |
| `DEFAULT_TIMEOUT` | `float` | `60.0` |
| `JSON_OUTPUT_SUFFIX` | `str` | `"Output JSON only, no markdown fences."` |
| `MAX_RETRIES` | `int` | `3` |
| `MAX_TRUNCATION_BUMPS` | `int` | `3` |
| `TRUNCATION_GROWTH_FACTOR` | `int` | `2` |
| `MAX_OUTPUT_TOKENS` | `int` | `32000` |
| `OutputTruncatedError` | class | `RuntimeError` subclass; raised when truncation bumps are exhausted |
| `resolve_api_key()` | `() -> str` | `TABULARIUS_API_KEY` → `OPENAI_API_KEY` fallback; raises `RuntimeError` if neither set |
| `LLMClient` | class | See below |

### LLMClient

| Method | Signature | Notes |
|--------|-----------|-------|
| `__init__` | `(*, api_key, base_url, model, max_tokens, timeout, client)` | Explicit kwargs win; otherwise `TABULARIUS_BASE_URL` / `TABULARIUS_MODEL` / `TABULARIUS_MAX_TOKENS` / `TABULARIUS_TIMEOUT` env vars; otherwise the `DEFAULT_*` constants. `client` injects a pre-built OpenAI SDK client (tests); otherwise builds one from env key |
| `chat` | `(messages, tools=None, *, max_tokens=None, timeout=None) -> response` | Always sends `response_format={"type": "json_object"}`; adds `tools` when provided; retries 429/5xx/timeout; raises `OutputTruncatedError` on persistent `finish_reason=length` |
| `_is_truncated` | `(response) -> bool` | `True` when `choices[0].finish_reason == "length"` |
| `_is_transient` | `(exc) -> bool` | 429 / 5xx / timeout transient; other 4xx not |
| `_with_json_system_prompt` | `(messages) -> messages` | Ensures first message is a system prompt ending in `JSON_OUTPUT_SUFFIX`; does not mutate input |

## Behavior Notes

- **Key resolution**: `TABULARIUS_API_KEY` wins; falls back to
  `OPENAI_API_KEY`; neither → clear `RuntimeError`.
- **Param resolution**: `LLMClient` kwargs beat `TABULARIUS_*` env vars,
  which beat the `DEFAULT_*` constants. `TABULARIUS_MAX_TOKENS` /
  `TABULARIUS_TIMEOUT` must parse as int / float — invalid values raise a
  clear `RuntimeError` naming the offending variable.
- **JSON constraint**: every request carries
  `response_format={"type": "json_object"}`; the system prompt is
  auto-appended with the JSON-only suffix. `content=None` in a system
  message is treated as empty, never crashes.
- **Retry**: exponential backoff `0.5s → 1s → 2s`, cap `8s`, max 3 retries.
  Retried: `RateLimitError` (429), `APIStatusError` with 5xx status,
  `APITimeoutError`. Other 4xx propagate immediately.
- **Truncation guard**: `finish_reason=length` is not success — `chat()`
  doubles the output budget (capped at `MAX_OUTPUT_TOKENS`) and retries up
  to `MAX_TRUNCATION_BUMPS` times, then raises `OutputTruncatedError`
  instead of returning an empty/partial payload for callers to parse.
- **No live calls in tests.** `_FakeOpenAI` scripts responses/exceptions.
