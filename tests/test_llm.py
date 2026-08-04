"""Tests for llm.py — API key resolution, JSON constraints, retry logic."""

from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError, APITimeoutError, RateLimitError

from tabularius import llm


class _FakeOpenAI:
    """Duck-typed OpenAI client recording calls and raising scripted errors."""

    def __init__(self, script: list[object]) -> None:
        self.script = list(script)
        self.calls: list[dict] = []
        self.chat = _FakeChat(self)


class _FakeChat:
    def __init__(self, parent: _FakeOpenAI) -> None:
        self.completions = _FakeCompletions(parent)


class _FakeCompletions:
    def __init__(self, parent: _FakeOpenAI) -> None:
        self._parent = parent

    def create(self, **kwargs: object) -> object:
        self._parent.calls.append(kwargs)
        item = self._parent.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _make_client(script: list[object]) -> tuple[llm.LLMClient, _FakeOpenAI]:
    fake = _FakeOpenAI(script)
    return llm.LLMClient(client=fake, api_key="k"), fake  # type: ignore[arg-type]


def _rate_limit_error() -> RateLimitError:
    req = httpx.Request("POST", "https://api.uniterra-solutions.com/v1/chat/completions")
    resp = httpx.Response(429, request=req)
    return RateLimitError("rate limited", response=resp, body={"error": {}})


def _status_error(status: int) -> APIStatusError:
    req = httpx.Request("POST", "https://api.uniterra-solutions.com/v1/chat/completions")
    resp = httpx.Response(status, request=req)
    return APIStatusError(f"status {status}", response=resp, body={"error": {}})


def _timeout_error() -> APITimeoutError:
    req = httpx.Request("POST", "https://api.uniterra-solutions.com/v1/chat/completions")
    return APITimeoutError(request=req)


class TestResolveApiKey:
    def test_tabularius_key_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TABULARIUS_API_KEY", "tab-key")
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
        assert llm.resolve_api_key() == "tab-key"

    def test_falls_back_to_openai_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TABULARIUS_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
        assert llm.resolve_api_key() == "openai-key"

    def test_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TABULARIUS_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="API key"):
            llm.resolve_api_key()


class TestEnvOverrides:
    def test_all_env_overrides_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TABULARIUS_BASE_URL", "http://localhost:9999/v1")
        monkeypatch.setenv("TABULARIUS_MODEL", "gpt-test")
        monkeypatch.setenv("TABULARIUS_MAX_TOKENS", "1234")
        monkeypatch.setenv("TABULARIUS_TIMEOUT", "12.5")
        client, _ = _make_client([{"ok": True}])
        assert client.base_url == "http://localhost:9999/v1"
        assert client.model == "gpt-test"
        assert client.max_tokens == 1234
        assert client.timeout == 12.5

    def test_defaults_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        names = (
            "TABULARIUS_BASE_URL",
            "TABULARIUS_MODEL",
            "TABULARIUS_MAX_TOKENS",
            "TABULARIUS_TIMEOUT",
        )
        for name in names:
            monkeypatch.delenv(name, raising=False)
        client, _ = _make_client([{"ok": True}])
        assert client.base_url == llm.DEFAULT_BASE_URL
        assert client.model == llm.DEFAULT_MODEL
        assert client.max_tokens == llm.DEFAULT_MAX_TOKENS
        assert client.timeout == llm.DEFAULT_TIMEOUT

    def test_explicit_kwargs_beat_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TABULARIUS_MODEL", "env-model")
        monkeypatch.setenv("TABULARIUS_MAX_TOKENS", "1111")
        fake = _FakeOpenAI([{"ok": True}])
        client = llm.LLMClient(client=fake, api_key="k", model="explicit", max_tokens=2222)  # type: ignore[arg-type]
        assert client.model == "explicit"
        assert client.max_tokens == 2222

    def test_invalid_max_tokens_env_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TABULARIUS_MAX_TOKENS", "not-a-number")
        with pytest.raises(RuntimeError, match="TABULARIUS_MAX_TOKENS"):
            _make_client([{"ok": True}])

    def test_invalid_timeout_env_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TABULARIUS_TIMEOUT", "soon")
        with pytest.raises(RuntimeError, match="TABULARIUS_TIMEOUT"):
            _make_client([{"ok": True}])


class TestJsonSystemPrompt:
    def test_suffix_added_to_system(self) -> None:
        messages = [{"role": "system", "content": "Be helpful."}]
        out = llm.LLMClient._with_json_system_prompt(messages)
        assert llm.JSON_OUTPUT_SUFFIX in out[0]["content"]
        assert "Be helpful" in out[0]["content"]

    def test_system_prepended_when_first_is_user(self) -> None:
        messages = [{"role": "user", "content": "hi"}]
        out = llm.LLMClient._with_json_system_prompt(messages)
        assert out[0]["role"] == "system"
        assert llm.JSON_OUTPUT_SUFFIX in out[0]["content"]
        assert out[1] == {"role": "user", "content": "hi"}

    def test_input_not_mutated(self) -> None:
        messages = [{"role": "system", "content": "Be helpful."}]
        llm.LLMClient._with_json_system_prompt(messages)
        assert messages == [{"role": "system", "content": "Be helpful."}]

    def test_none_system_content_does_not_raise(self) -> None:
        # content=None must be treated as empty, not crash the suffix append.
        out = llm.LLMClient._with_json_system_prompt([{"role": "system", "content": None}])
        assert llm.JSON_OUTPUT_SUFFIX in out[0]["content"]


def _truncated_response() -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason="length", message=None)])


class TestTruncationGuard:
    def test_truncation_bumps_max_tokens_and_recovers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(llm.time, "sleep", lambda _: None)
        client, fake = _make_client([_truncated_response(), _truncated_response(), {"ok": True}])
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result == {"ok": True}
        assert [call["max_tokens"] for call in fake.calls] == [
            llm.DEFAULT_MAX_TOKENS,
            llm.DEFAULT_MAX_TOKENS * llm.TRUNCATION_GROWTH_FACTOR,
            llm.DEFAULT_MAX_TOKENS * llm.TRUNCATION_GROWTH_FACTOR**2,
        ]

    def test_truncation_exhausts_bumps_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm.time, "sleep", lambda _: None)
        client, fake = _make_client([_truncated_response()] * (llm.MAX_TRUNCATION_BUMPS + 1))
        with pytest.raises(llm.OutputTruncatedError, match="finish_reason=length"):
            client.chat([{"role": "user", "content": "hi"}])
        assert len(fake.calls) == llm.MAX_TRUNCATION_BUMPS + 1

    def test_truncation_error_mentions_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm.time, "sleep", lambda _: None)
        client, _ = _make_client([_truncated_response()] * (llm.MAX_TRUNCATION_BUMPS + 1))
        with pytest.raises(llm.OutputTruncatedError, match="TABULARIUS_MAX_TOKENS"):
            client.chat([{"role": "user", "content": "hi"}])

    def test_truncation_capped_at_max_output_tokens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm.time, "sleep", lambda _: None)
        fake = _FakeOpenAI([_truncated_response()])
        client = llm.LLMClient(client=fake, api_key="k", max_tokens=llm.MAX_OUTPUT_TOKENS)  # type: ignore[arg-type]
        with pytest.raises(llm.OutputTruncatedError):
            client.chat([{"role": "user", "content": "hi"}])
        assert len(fake.calls) == 1

    def test_normal_response_passes_through(self) -> None:
        client, _ = _make_client([{"ok": True}])
        assert client.chat([{"role": "user", "content": "hi"}]) == {"ok": True}


class TestChatRetry:
    def test_retries_on_429_then_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr(llm.time, "sleep", sleeps.append)
        client, fake = _make_client([_rate_limit_error(), _rate_limit_error(), {"ok": True}])
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result == {"ok": True}
        assert len(fake.calls) == 3
        assert sleeps == [llm.RETRY_BASE_DELAY, llm.RETRY_BASE_DELAY * 2]

    def test_retries_on_5xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm.time, "sleep", lambda _: None)
        client, fake = _make_client([_status_error(503), {"ok": True}])
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result == {"ok": True}
        assert len(fake.calls) == 2

    def test_retries_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm.time, "sleep", lambda _: None)
        client, fake = _make_client([_timeout_error(), {"ok": True}])
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result == {"ok": True}

    def test_gives_up_after_max_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm.time, "sleep", lambda _: None)
        client, fake = _make_client([_rate_limit_error()] * (llm.MAX_RETRIES + 1))
        with pytest.raises(RateLimitError):
            client.chat([{"role": "user", "content": "hi"}])
        assert len(fake.calls) == llm.MAX_RETRIES + 1

    def test_does_not_retry_4xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm.time, "sleep", lambda _: None)
        client, fake = _make_client([_status_error(400)])
        with pytest.raises(APIStatusError) as exc_info:
            client.chat([{"role": "user", "content": "hi"}])
        assert exc_info.value.status_code == 400
        assert len(fake.calls) == 1

    def test_request_has_json_object_and_tools(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeOpenAI([{"ok": True}])
        client = llm.LLMClient(client=fake, api_key="k")  # type: ignore[arg-type]
        tools = [{"type": "function", "function": {"name": "f"}}]
        client.chat([{"role": "user", "content": "hi"}], tools=tools)
        sent = fake.calls[0]
        assert sent["response_format"] == {"type": "json_object"}
        assert sent["tools"] == tools
        assert sent["model"] == llm.DEFAULT_MODEL
        assert sent["max_tokens"] == llm.DEFAULT_MAX_TOKENS
