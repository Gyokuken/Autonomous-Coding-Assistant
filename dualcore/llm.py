"""Groq LLM client wrapper.

Centralises model/token config and exposes both a blocking ``complete`` and a
token-level ``stream``. The rest of the app depends on the :class:`LLM` protocol,
not on Groq directly, which keeps the orchestrator unit-testable with a fake.
"""

from __future__ import annotations

from typing import Iterator, Protocol, Sequence

from groq import Groq

from .config import ConfigError, Settings, model_token_cap

Message = dict[str, str]


class LLM(Protocol):
    """Minimal interface the orchestrator needs from a language model."""

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        *,
        temperature: float | None = ...,
        max_tokens: int | None = ...,
        model: str | None = ...,
    ) -> str: ...

    def stream(
        self,
        system: str,
        messages: Sequence[Message],
        *,
        temperature: float | None = ...,
        max_tokens: int | None = ...,
        model: str | None = ...,
    ) -> Iterator[str]: ...


class GroqLLM:
    """Concrete :class:`LLM` backed by the Groq API."""

    def __init__(self, settings: Settings) -> None:
        if not settings.groq_api_key:
            raise ConfigError(
                "GROQ_API_KEY is not set. Get a free key at https://console.groq.com "
                "and add it to your .env file."
            )
        self._client = Groq(api_key=settings.groq_api_key)
        self._settings = settings

    def _build(self, system: str, messages: Sequence[Message]) -> list[Message]:
        return [{"role": "system", "content": system}, *messages]

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> str:
        chosen = model or self._settings.model
        requested = max_tokens or self._settings.max_tokens
        resp = self._client.chat.completions.create(
            model=chosen,
            max_tokens=min(requested, model_token_cap(chosen)),
            temperature=self._settings.temperature if temperature is None else temperature,
            messages=self._build(system, messages),
        )
        return resp.choices[0].message.content or ""

    def stream(
        self,
        system: str,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> Iterator[str]:
        chosen = model or self._settings.model
        requested = max_tokens or self._settings.max_tokens
        stream = self._client.chat.completions.create(
            model=chosen,
            max_tokens=min(requested, model_token_cap(chosen)),
            temperature=self._settings.temperature if temperature is None else temperature,
            messages=self._build(system, messages),
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
