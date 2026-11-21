"""One OpenAI-compatible chat call (ADR 0002). Groq in the cluster, KodeKey on the laptop: both
serve gpt-oss-120b behind the same API, so the provider is configuration, not code.

No retries on purpose: a 429 means "wait", and a retry would break the 8-second target.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

import httpx

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODELS = {"groq": "openai/gpt-oss-120b", "kodekey": "gpt-oss-120b"}
TIMEOUT = httpx.Timeout(7.0, connect=3.0)


class LLMError(RuntimeError):
    reason = "provider_error"


class RateLimited(LLMError):
    reason = "rate_limited"


class LLMTimeout(LLMError):
    reason = "timeout"


class ProviderError(LLMError):
    reason = "provider_error"


class BadResponse(LLMError):
    reason = "bad_response"


class ConfigError(RuntimeError):
    """Missing or wrong settings: the app cannot answer at all."""


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    base_url: str
    api_key: str = field(repr=False)  # never printed, never logged
    model: str
    max_tokens: int = 500
    reasoning_effort: str = "low"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LLMSettings:
        env = os.environ if env is None else env
        provider = env.get("LLM_PROVIDER", "groq")
        if provider == "groq":
            key_var, base_url = "GROQ_API_KEY", env.get("GROQ_BASE_URL", GROQ_BASE_URL)
        elif provider == "kodekey":
            # The development and eval key: laptop and CI only, never the cluster (ADR 0025).
            key_var, base_url = "KODEKEY_API_KEY", env.get("KODEKEY_BASE_URL", "")
            if not base_url:
                raise ConfigError("KODEKEY_BASE_URL is not set")
        else:
            raise ConfigError(f"LLM_PROVIDER must be groq or kodekey, not {provider!r}")
        key = env.get(key_var, "")
        if not key:
            raise ConfigError(f"{key_var} is not set")
        model = env.get("LLM_MODEL") or DEFAULT_MODELS[provider]
        return cls(provider, base_url.rstrip("/"), key, model)


@dataclass(frozen=True)
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int


def chat(
    settings: LLMSettings, messages: list[dict[str, str]], *, client: httpx.Client | None = None
) -> Completion:
    body = {
        "model": settings.model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": settings.max_tokens,
        "reasoning_effort": settings.reasoning_effort,
    }
    headers = {"Authorization": f"Bearer {settings.api_key}"}
    own = client is None
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        resp = http.post(f"{settings.base_url}/chat/completions", json=body, headers=headers)
    except httpx.TimeoutException as e:
        raise LLMTimeout(f"{settings.provider}: no answer in time") from e
    except httpx.HTTPError as e:
        raise ProviderError(f"{settings.provider}: {type(e).__name__}") from e
    finally:
        if own:
            http.close()
    if resp.status_code == 429:
        raise RateLimited(f"{settings.provider}: rate limited")
    if resp.status_code >= 400:
        # 5xx: their problem; 4xx other than 429: ours (key, model name). Both: no answer now.
        raise ProviderError(f"{settings.provider}: HTTP {resp.status_code}")
    try:
        data = resp.json()
        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage") or {}
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise BadResponse(f"{settings.provider}: unexpected reply shape") from e
    if not text.strip():
        raise BadResponse(f"{settings.provider}: empty answer")
    return Completion(
        text, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    )
