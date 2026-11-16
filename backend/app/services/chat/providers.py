"""Streaming adapters for Groq, Gemini and Ollama with a common error taxonomy.

Every adapter yields text deltas and raises `ProviderFailure` with a `kind` the
fallback router uses to decide how long to skip that provider/model.
"""

from __future__ import annotations

import base64
import contextlib
import json
import re
import time
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


TEXT, REASONING = "text", "reasoning"
REASONING_MODELS = re.compile(r"qwen3|qwq|deepseek|gpt-oss|r1\b|magistral|phi-?4-reason", re.I)


class ThinkSplitter:
    """Splits a streamed answer into reasoning and text around <think>...</think> tags.

    Tags may arrive split across chunks, so a possible partial tag is held back.
    """

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self.buffer = ""
        self.inside = False

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        self.buffer += chunk
        out: list[tuple[str, str]] = []
        while self.buffer:
            tag = self.CLOSE if self.inside else self.OPEN
            index = self.buffer.find(tag)
            if index >= 0:
                if index:
                    out.append((REASONING if self.inside else TEXT, self.buffer[:index]))
                self.buffer = self.buffer[index + len(tag) :]
                self.inside = not self.inside
                continue
            keep = next((n for n in range(len(tag) - 1, 0, -1) if self.buffer.endswith(tag[:n])), 0)
            emit = self.buffer[: len(self.buffer) - keep]
            if emit:
                out.append((REASONING if self.inside else TEXT, emit))
            self.buffer = self.buffer[len(self.buffer) - keep :]
            break
        return out

    def flush(self) -> list[tuple[str, str]]:
        rest, self.buffer = self.buffer, ""
        return [(REASONING if self.inside else TEXT, rest)] if rest else []


async def _stream_http(
    url: str, payload: dict, headers: dict, parse, timeout: float
) -> AsyncIterator[tuple[str, str]]:
    splitter = ThinkSplitter()
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
                reasoning, text = parse(line)
                if reasoning:
                    yield REASONING, reasoning
                for piece in splitter.feed(text) if text else ():
                    yield piece
            for piece in splitter.flush():
                yield piece
    except httpx.TimeoutException as exc:
        raise ProviderFailure("timeout", "Provider timed out") from exc
    except httpx.HTTPError as exc:
        raise ProviderFailure("unavailable", "Provider connection failed") from exc


def _parse_groq(line: str) -> tuple[str, str]:
    if not line.startswith("data:"):
        return "", ""
    data = line[5:].strip()
    if not data or data == "[DONE]":
        return "", ""
    try:
        event = json.loads(data)
    except ValueError:
        return "", ""
    if event.get("error"):
        raise ProviderFailure("unavailable", "Provider stopped generation")
    choices = event.get("choices") or []
    delta = (choices[0].get("delta") or {}) if choices else {}
    return delta.get("reasoning") or "", delta.get("content") or ""


def _parse_ollama(line: str) -> tuple[str, str]:
    if not line.strip():
        return "", ""
    try:
        event = json.loads(line)
    except ValueError:
        return "", ""
    if event.get("error"):
        raise ProviderFailure("unavailable", "Ollama reported an error")
    message = event.get("message") or {}
    return message.get("thinking") or "", message.get("content") or ""


async def stream_groq(model, system, history, image) -> AsyncIterator[tuple[str, str]]:
    settings = get_settings()
    payload = {
        "model": model,
        "messages": _openai_messages(system, history, image, "groq"),
        "stream": True,
        "max_completion_tokens": 4000,
        "temperature": 0.3,
    }
    headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
    url = "https://api.groq.com/openai/v1/chat/completions"
    async for piece in _reasoning_first(
        model, url, payload, {"reasoning_format": "parsed"}, headers, _parse_groq
    ):
        yield piece


async def _reasoning_first(model, url, payload, option, headers, parse):
    """Ask reasoning models to return their thinking separately; models that reject the
    option are retried without it (raw <think> tags are still split out of the text)."""
    timeout = get_settings().llm_timeout_seconds
    if REASONING_MODELS.search(model):
        produced = False
        try:
            async for piece in _stream_http(url, {**payload, **option}, headers, parse, timeout):
                produced = True
                yield piece
            return
        except ProviderFailure as failure:
            if produced or failure.kind != "bad_request":
                raise
    async for piece in _stream_http(url, payload, headers, parse, timeout):
        yield piece


async def stream_ollama(model, system, history, image) -> AsyncIterator[tuple[str, str]]:
    settings = get_settings()
    headers = (
        {"Authorization": f"Bearer {settings.ollama_api_key}"} if settings.ollama_api_key else {}
    )
    payload = {
        "model": model,
        "messages": _openai_messages(system, history, image, "ollama"),
        "stream": True,
    }
    async for piece in _reasoning_first(
        model,
        f"{settings.ollama_base_url}/api/chat",
        payload,
        {"think": True},
        headers,
        _parse_ollama,
    ):
        yield piece


async def stream_gemini(model, system, history, image) -> AsyncIterator[tuple[str, str]]:
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

    def config(thoughts: bool):
        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.3,
            thinking_config=types.ThinkingConfig(include_thoughts=True) if thoughts else None,
        )

    produced = False
    try:
        for thoughts in (True, False):
            try:
                stream = await client.aio.models.generate_content_stream(
                    model=model, contents=contents, config=config(thoughts)
                )
                async for chunk in stream:
                    for candidate in chunk.candidates or []:
                        for part in (candidate.content.parts if candidate.content else None) or []:
                            if not part.text:
                                continue
                            produced = True
                            yield (REASONING if part.thought else TEXT), part.text
                return
            except genai_errors.APIError as exc:
                # Models without thinking support reject include_thoughts: retry without it.
                if thoughts and not produced and int(exc.code or 0) == 400:
                    continue
                raise
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


_ollama_checked: dict[str, tuple[float, set[str]]] = {}
OLLAMA_CHECK_EVERY = 10.0  # seconds; the check runs before answers, so keep it rare and quick


def _ollama_names(model: str) -> set[str]:
    return {model, model if ":" in model else f"{model}:latest"}


async def ollama_has_model(model: str) -> bool:
    """Whether the Ollama server answers and lists `model` (GET /api/tags, 3 s, cached 10 s)."""
    settings = get_settings()
    base = settings.ollama_base_url
    if not base:
        return False
    now = time.monotonic()
    checked = _ollama_checked.get(base)
    if checked is None or now - checked[0] >= OLLAMA_CHECK_EVERY:
        names: set[str] = set()
        headers = (
            {"Authorization": f"Bearer {settings.ollama_api_key}"}
            if settings.ollama_api_key
            else {}
        )
        try:
            async with httpx.AsyncClient(timeout=3, follow_redirects=False) as client:
                response = await client.get(f"{base}/api/tags", headers=headers)
            if response.status_code == 200:
                for item in response.json().get("models") or []:
                    names.update(str(item.get(k, "")) for k in ("name", "model"))
        except (httpx.HTTPError, ValueError):
            pass
        checked = (now, names)
        _ollama_checked[base] = checked
    return bool(_ollama_names(model) & checked[1])


def configured(provider: str) -> bool:
    settings = get_settings()
    return {
        "groq": bool(settings.groq_api_key),
        "gemini": bool(settings.gemini_api_key),
        "ollama": bool(settings.ollama_base_url),
    }.get(provider, False)


def candidates(vision: bool = False) -> list[Candidate]:
    """Fallback chain. With an image, only vision-capable models in LLM_VISION_ORDER."""
    settings = get_settings()
    models = {
        "groq": settings.groq_vision_models if vision else settings.groq_models,
        "gemini": settings.gemini_models,
        "ollama": settings.ollama_models,
    }
    order = settings.llm_vision_order if vision else settings.llm_fallback_order
    return [
        Candidate(provider, model)
        for provider in order
        if provider in ADAPTERS and configured(provider)
        for model in models[provider]
    ]
