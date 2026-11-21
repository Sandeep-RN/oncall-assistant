import json

import httpx
import pytest

from app.answer.llm import (
    BadResponse,
    ConfigError,
    LLMSettings,
    LLMTimeout,
    ProviderError,
    RateLimited,
    chat,
)

SETTINGS = LLMSettings(
    provider="fake", base_url="https://llm.test/v1", api_key="k", model="m", max_tokens=100
)
MESSAGES = [{"role": "user", "content": "hi"}]


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def ok(content="An answer [1].", usage=None):
    body = {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": usage or {"prompt_tokens": 50, "completion_tokens": 10},
    }
    return lambda request: httpx.Response(200, json=body)


def test_sends_an_openai_compatible_request_and_reads_the_answer():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return ok()(request)

    out = chat(SETTINGS, MESSAGES, client=client(handler))
    assert seen["url"] == "https://llm.test/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "m" and seen["body"]["temperature"] == 0
    assert seen["body"]["reasoning_effort"] == "low"
    assert (out.text, out.prompt_tokens, out.completion_tokens) == ("An answer [1].", 50, 10)


@pytest.mark.parametrize(
    "status, error",
    [(429, RateLimited), (500, ProviderError), (503, ProviderError), (401, ProviderError)],
)
def test_error_statuses_map_to_their_error(status, error):
    with pytest.raises(error):
        chat(SETTINGS, MESSAGES, client=client(lambda r: httpx.Response(status, json={})))


def test_a_timeout_is_its_own_error():
    def slow(request):
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(LLMTimeout):
        chat(SETTINGS, MESSAGES, client=client(slow))


def test_a_connection_failure_is_a_provider_error():
    def down(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProviderError):
        chat(SETTINGS, MESSAGES, client=client(down))


@pytest.mark.parametrize(
    "body", [{"choices": []}, {"nothing": 1}, {"choices": [{"message": {"content": "  "}}]}]
)
def test_malformed_or_empty_replies_are_bad_responses(body):
    with pytest.raises(BadResponse):
        chat(SETTINGS, MESSAGES, client=client(lambda r: httpx.Response(200, json=body)))


def test_settings_from_env_pick_the_provider(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g-key")
    s = LLMSettings.from_env({"GROQ_API_KEY": "g-key"})
    assert s.provider == "groq" and s.base_url.startswith("https://api.groq.com")
    assert s.model == "openai/gpt-oss-120b"
    k = LLMSettings.from_env(
        {"LLM_PROVIDER": "kodekey", "KODEKEY_API_KEY": "k", "KODEKEY_BASE_URL": "https://kk/v1"}
    )
    assert (k.base_url, k.model) == ("https://kk/v1", "gpt-oss-120b")


def test_missing_key_is_a_config_error_and_the_key_is_never_shown():
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        LLMSettings.from_env({})
    s = LLMSettings.from_env({"GROQ_API_KEY": "secret-value"})
    assert "secret-value" not in repr(s)
