"""OpenAI SDK wrapper pointed at the uniterra relay.

Handles API key resolution, JSON output constraints, and transient-error
retry for every tabularius agent call.
"""

from __future__ import annotations

import os
import time
from typing import Any

from openai import APIStatusError, APITimeoutError, OpenAI, RateLimitError

DEFAULT_BASE_URL = "https://api.uniterra-solutions.com/v1"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_MAX_TOKENS = 2000
DEFAULT_TIMEOUT = 60.0
JSON_OUTPUT_SUFFIX = "Output JSON only, no markdown fences."

RETRY_BASE_DELAY = 0.5
RETRY_MAX_DELAY = 8.0
MAX_RETRIES = 3

# Truncation guard: `finish_reason=length` is not success. `chat()` doubles
# the output budget (capped at MAX_OUTPUT_TOKENS) and retries; after
# MAX_TRUNCATION_BUMPS it raises OutputTruncatedError instead of returning a
# partial payload for callers to parse.
MAX_TRUNCATION_BUMPS = 3
TRUNCATION_GROWTH_FACTOR = 2
MAX_OUTPUT_TOKENS = 32000

_TRANSIENT_5XX = frozenset(range(500, 600))


class OutputTruncatedError(RuntimeError):
    """Model output hit ``max_tokens`` (``finish_reason=length``) and the
    automatic budget bumps were exhausted."""


def _env_int(name: str, default: int) -> int:
    """Parse an integer env var, falling back to ``default`` when unset."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from None


def _env_float(name: str, default: float) -> float:
    """Parse a float env var, falling back to ``default`` when unset."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be a number, got {raw!r}") from None


def resolve_api_key() -> str:
    """Return the relay API key from env (TABULARIUS_API_KEY, then OPENAI_API_KEY)."""
    key = os.environ.get("TABULARIUS_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("no API key found: set TABULARIUS_API_KEY or OPENAI_API_KEY")
    return key


class LLMClient:
    """Thin OpenAI chat-completions client with JSON + retry constraints."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        client: OpenAI | None = None,
    ) -> None:
        """Explicit kwargs win; otherwise ``TABULARIUS_*`` env vars; otherwise
        the ``DEFAULT_*`` constants (backward compatible)."""
        self.base_url = base_url or os.environ.get("TABULARIUS_BASE_URL") or DEFAULT_BASE_URL
        self.model = model or os.environ.get("TABULARIUS_MODEL") or DEFAULT_MODEL
        self.max_tokens = max_tokens or _env_int("TABULARIUS_MAX_TOKENS", DEFAULT_MAX_TOKENS)
        self.timeout = timeout or _env_float("TABULARIUS_TIMEOUT", DEFAULT_TIMEOUT)
        self._client = client or OpenAI(
            base_url=self.base_url,
            api_key=api_key or resolve_api_key(),
            timeout=self.timeout,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Call chat.completions with JSON constraints and transient retry.

        Returns the raw response object (choices[0].message drives the
        agent loop). Retries 429 / 5xx / timeout with exponential
        backoff (0.5s start, 8s cap, max 3 retries).

        Truncation guard: a response with ``finish_reason=length`` is not
        treated as success — the output budget is doubled and the request is
        retried (capped at ``MAX_OUTPUT_TOKENS``, up to
        ``MAX_TRUNCATION_BUMPS`` times) before ``OutputTruncatedError`` is
        raised, so callers never parse an empty/partial payload.
        """
        request: dict[str, Any] = {
            "model": self.model,
            "messages": self._with_json_system_prompt(messages),
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens or self.max_tokens,
        }
        if tools:
            request["tools"] = tools

        delay = RETRY_BASE_DELAY
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self._client.chat.completions.create(
                    **request, timeout=timeout or self.timeout
                )
                break
            except (RateLimitError, APIStatusError, APITimeoutError) as exc:
                if not self._is_transient(exc):
                    raise
                if attempt >= MAX_RETRIES:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, RETRY_MAX_DELAY)
        else:  # pragma: no cover - the loop always breaks or raises
            raise AssertionError("unreachable")

        truncations = 0
        while self._is_truncated(response):
            if truncations >= MAX_TRUNCATION_BUMPS or request["max_tokens"] >= MAX_OUTPUT_TOKENS:
                raise OutputTruncatedError(
                    f"output truncated (finish_reason=length) after {truncations} "
                    f"max_tokens bump(s); increase TABULARIUS_MAX_TOKENS "
                    f"(current max_tokens={request['max_tokens']})"
                )
            truncations += 1
            request["max_tokens"] = min(
                request["max_tokens"] * TRUNCATION_GROWTH_FACTOR, MAX_OUTPUT_TOKENS
            )
            response = self._client.chat.completions.create(
                **request, timeout=timeout or self.timeout
            )
        return response

    @staticmethod
    def _is_truncated(response: Any) -> bool:
        """True when the model hit ``max_tokens`` (``finish_reason=length``)."""
        choices: Any = getattr(response, "choices", None)
        if not choices:
            return False
        return getattr(choices[0], "finish_reason", None) == "length"

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        """429 / 5xx / timeout are transient; 4xx (except 429) are not."""
        if isinstance(exc, (RateLimitError, APITimeoutError)):
            return True
        return isinstance(exc, APIStatusError) and exc.status_code in _TRANSIENT_5XX

    @staticmethod
    def _with_json_system_prompt(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Ensure the first message is a system prompt requesting JSON only."""
        out = [dict(m) for m in messages]
        if not out:
            out = [{"role": "system", "content": ""}]
        if out[0].get("role") != "system":
            out.insert(0, {"role": "system", "content": ""})
        content = out[0].get("content") or ""
        if JSON_OUTPUT_SUFFIX not in content:
            out[0]["content"] = f"{content}\n\n{JSON_OUTPUT_SUFFIX}"
        return out
