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
JSON_OUTPUT_SUFFIX = "Output JSON only, no markdown fences."

RETRY_BASE_DELAY = 0.5
RETRY_MAX_DELAY = 8.0
MAX_RETRIES = 3

_TRANSIENT_5XX = frozenset(range(500, 600))


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
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float = 60.0,
        client: OpenAI | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = client or OpenAI(
            base_url=base_url,
            api_key=api_key or resolve_api_key(),
            timeout=timeout,
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
                return self._client.chat.completions.create(
                    **request, timeout=timeout or self.timeout
                )
            except (RateLimitError, APIStatusError, APITimeoutError) as exc:
                if not self._is_transient(exc):
                    raise
                if attempt >= MAX_RETRIES:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, RETRY_MAX_DELAY)
        raise AssertionError("unreachable")

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
        content = out[0].get("content", "")
        if JSON_OUTPUT_SUFFIX not in content:
            out[0]["content"] = f"{content}\n\n{JSON_OUTPUT_SUFFIX}"
        return out
