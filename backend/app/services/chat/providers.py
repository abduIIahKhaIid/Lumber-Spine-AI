"""Streaming adapters for Groq, Gemini and Ollama with a common error taxonomy.

Every adapter yields text deltas and raises `ProviderFailure` with a `kind` the
fallback router uses to decide how long to skip that provider/model.
"""

from __future__ import annotations

import base64
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from app.core.config import get_settings


class ProviderFailure(Exception):
    """kind: rate_limit | auth | not_found | bad_request | unavailable | timeout | empty"""

    def __init__(self, kind: str, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after


@dataclass(frozen=True)
class Candidate:
    provider: str
    model: str

    @property
    def label(self) -> str:
        return f"{PROVIDER_NAMES[self.provider]} · {self.model}"


PROVIDER_NAMES = {"groq": "Groq", "gemini": "Gemini", "ollama": "Ollama"}


def _retry_after(headers) -> float | None:
    try:
        return float(headers.get("retry-after")) if headers.get("retry-after") else None
    except (TypeError, ValueError):
        return None


def _http_failure(status: int, headers=None) -> ProviderFailure:
    if status == 429:
        return ProviderFailure("rate_limit", "Rate limit reached", _retry_after(headers or {}))
    if status in (401, 403):
        return ProviderFailure("auth", "API key rejected or access denied")
    if status == 404:
        return ProviderFailure("not_found", "Model or endpoint not found")
    if status in (400, 413, 422):
        return ProviderFailure("bad_request", "Request rejected (model may not support images)")
    return ProviderFailure("unavailable", f"Provider error (HTTP {status})")


def _openai_messages(system: str, history: list[dict], image: str | None, provider: str):
    messages = [{"role": "system", "content": system}]
    for index, item in enumerate(history):
        last = index == len(history) - 1
        if last and image and item["role"] == "user":
            if provider == "ollama":
                messages.append({"role": "user", "content": item["content"], "images": [image]})
            else:
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": item["content"]},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image}"},
                            },
                        ],
                    }
                )
        else:
            messages.append({"role": item["role"], "content": item["content"]})
    return messages


async def _stream_http(
    url: str, payload: dict, headers: dict, parse, timeout: float
) -> AsyncIterator[str]:
    try:
        async with (
            httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=8), follow_redirects=False
            ) as client,
            client.stream("POST", url, json=payload, headers=headers) as response,
        ):
            if response.status_code != 200:
                raise _http_failure(response.status_code, response.headers)
            async for line in response.aiter_lines():
                delta = parse(line)
                if delta:
                    yield delta
    except httpx.TimeoutException as exc:
        raise ProviderFailure("timeout", "Provider timed out") from exc
    except httpx.HTTPError as exc:
        raise ProviderFailure("unavailable", "Provider connection failed") from exc


def _parse_groq(line: str) -> str:
    if not line.startswith("data:"):
        return ""
    data = line[5:].strip()
    if not data or data == "[DONE]":
        return ""
    try:
        event = json.loads(data)
    except ValueError:
        return ""
    if event.get("error"):
        raise ProviderFailure("unavailable", "Provider stopped generation")
    choices = event.get("choices") or []
    return (choices[0].get("delta") or {}).get("content") or "" if choices else ""


def _parse_ollama(line: str) -> str:
    if not line.strip():
        return ""
    try:
        event = json.loads(line)
    except ValueError:
        return ""
    if event.get("error"):
        raise ProviderFailure("unavailable", "Ollama reported an error")
    return (event.get("message") or {}).get("content") or ""


async def stream_groq(model, system, history, image) -> AsyncIterator[str]:
    settings = get_settings()
    payload = {
        "model": model,
        "messages": _openai_messages(system, history, image, "groq"),
        "stream": True,
        "max_completion_tokens": 1500,
        "temperature": 0.3,
    }
    headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
    async for delta in _stream_http(
        "https://api.groq.com/openai/v1/chat/completions",
        payload,
        headers,
        _parse_groq,
        settings.llm_timeout_seconds,
    ):
        yield delta


async def stream_ollama(model, system, history, image) -> AsyncIterator[str]:
    settings = get_settings()
    headers = (
        {"Authorization": f"Bearer {settings.ollama_api_key}"} if settings.ollama_api_key else {}
    )
    payload = {
        "model": model,
        "messages": _openai_messages(system, history, image, "ollama"),
        "stream": True,
    }
    async for delta in _stream_http(
        f"{settings.ollama_base_url}/api/chat",
        payload,
        headers,
        _parse_ollama,
        settings.llm_timeout_seconds,
    ):
        yield delta


async def stream_gemini(model, system, history, image) -> AsyncIterator[str]:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types

    settings = get_settings()
    client = genai.Client(api_key=settings.gemini_api_key)
    contents = []
    for index, item in enumerate(history):
        parts = [types.Part(text=item["content"])]
        if image and index == len(history) - 1 and item["role"] == "user":
            parts.append(
                types.Part.from_bytes(data=base64.b64decode(image), mime_type="image/jpeg")
            )
        contents.append(
            types.Content(role="user" if item["role"] == "user" else "model", parts=parts)
        )
    try:
        stream = await client.aio.models.generate_content_stream(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0.3),
        )
        async for chunk in stream:
            if chunk.text:
                yield chunk.text
    except genai_errors.APIError as exc:
        raise _http_failure(int(exc.code or 500)) from exc
    except (httpx.TimeoutException, TimeoutError) as exc:
        raise ProviderFailure("timeout", "Provider timed out") from exc
    except httpx.HTTPError as exc:
        raise ProviderFailure("unavailable", "Provider connection failed") from exc
    finally:
        with contextlib.suppress(Exception):
            await client.aio.aclose()


ADAPTERS = {"groq": stream_groq, "gemini": stream_gemini, "ollama": stream_ollama}


def configured(provider: str) -> bool:
    settings = get_settings()
    return {
        "groq": bool(settings.groq_api_key),
        "gemini": bool(settings.gemini_api_key),
        "ollama": bool(settings.ollama_base_url),
    }.get(provider, False)


def candidates() -> list[Candidate]:
    settings = get_settings()
    models = {
        "groq": settings.groq_models,
        "gemini": settings.gemini_models,
        "ollama": settings.ollama_models,
    }
    return [
        Candidate(provider, model)
        for provider in settings.llm_fallback_order
        if provider in ADAPTERS and configured(provider)
        for model in models[provider]
    ]
