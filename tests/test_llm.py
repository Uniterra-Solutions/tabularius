"""Tests for llm.py — API key resolution, JSON constraints, retry logic."""

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
