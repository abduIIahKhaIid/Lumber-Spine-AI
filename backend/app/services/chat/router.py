"""Automatic LLM fallback: try each provider/model in order, skip the ones cooling down.

A rate limit, timeout, outage or bad key moves the request to the next candidate
without any user action. Failed candidates are skipped for a while so the next
message does not wait on a provider that just failed.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from threading import Lock

from app.core.config import get_settings
from app.services.chat import providers
from app.services.chat.providers import Candidate, ProviderFailure

COOLDOWN_SECONDS = {
    "rate_limit": 60,
    "timeout": 30,
    "unavailable": 30,
    "empty": 15,
    "auth": 600,
    "not_found": 3600,
    "bad_request": 0,  # request-specific (e.g. an image to a text-only model): no cooldown
}
# Ollama is the user's own server: a missing model is fixed with `ollama pull` and a refused
# connection by restarting the tunnel, usually within a minute. Long cloud-style cooldowns
# would keep it out of the chain long after it works again, so they are short here, and a
# cooling Ollama model is re-checked (see `providers.ollama_has_model`) before it is skipped.
PROVIDER_COOLDOWN_SECONDS = {"ollama": {"not_found": 60, "auth": 60}}
# Failures that a quick Ollama check can clear early.
RECHECKABLE = {"not_found", "auth", "unavailable", "timeout"}
FRIENDLY = {
    "rate_limit": "rate limit reached",
    "timeout": "timed out",
    "unavailable": "service unavailable",
    "auth": "API key rejected",
    "not_found": "model not found",
    "bad_request": "request not supported",
    "empty": "returned an empty answer",
}


class Cooldowns:
    def __init__(self):
        self._until: dict[str, tuple[float, str]] = {}
        self._lock = Lock()

    @staticmethod
    def _keys(candidate: Candidate) -> tuple[str, str]:
        return candidate.provider, f"{candidate.provider}:{candidate.model}"

    def blocked(self, candidate: Candidate) -> float:
        now = time.monotonic()
        with self._lock:
            return max(
                0.0,
                *(self._until.get(key, (0, ""))[0] - now for key in self._keys(candidate)),
            )

    def reason(self, candidate: Candidate) -> str:
        """The failure kind behind the longest active cooldown of this candidate."""
        now = time.monotonic()
        with self._lock:
            active = [self._until[k] for k in self._keys(candidate) if k in self._until]
        active = [entry for entry in active if entry[0] > now]
        return max(active)[1] if active else ""

    def penalize(self, candidate: Candidate, failure: ProviderFailure) -> None:
        table = {**COOLDOWN_SECONDS, **PROVIDER_COOLDOWN_SECONDS.get(candidate.provider, {})}
        seconds = failure.retry_after or table.get(failure.kind, 30)
        if seconds <= 0:
            return
        provider_key, model_key = self._keys(candidate)
        # Keys and quota are per provider; a missing model or overload is per model.
        key = provider_key if failure.kind in ("auth",) else model_key
        with self._lock:
            self._until[key] = (time.monotonic() + min(seconds, 3600), failure.kind)

    def lift(self, candidate: Candidate) -> None:
        with self._lock:
            for key in self._keys(candidate):
                self._until.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._until.clear()

    def snapshot(self) -> dict[str, int]:
        now = time.monotonic()
        with self._lock:
            return {k: int(v[0] - now) for k, v in self._until.items() if v[0] > now}


async def _recovered(candidate: Candidate) -> bool:
    """A cooling Ollama model that is reachable and pulled again is tried right away."""
    if candidate.provider != "ollama" or cooldowns.reason(candidate) not in RECHECKABLE:
        return False
    if await providers.ollama_has_model(candidate.model):
        cooldowns.lift(candidate)
        return True
    return False


cooldowns = Cooldowns()


async def _pieces(candidate: Candidate, system: str, history: list[dict], image: str | None):
    """The adapter's stream, failing with `timeout` when the model sends nothing for
    LLM_TIMEOUT_SECONDS (default 90): before its first token (thinking counts) or mid-answer.
    The router then moves on to the next model."""
    limit = get_settings().llm_timeout_seconds
    stream = providers.ADAPTERS[candidate.provider](candidate.model, system, history, image)
    try:
        while True:
            try:
                piece = await asyncio.wait_for(anext(stream), timeout=limit)
            except StopAsyncIteration:
                return
            except TimeoutError as exc:
                raise ProviderFailure("timeout", f"no response in {limit} s") from exc
            yield piece
    finally:
        with contextlib.suppress(Exception):
            await stream.aclose()


@dataclass
class Step:
    provider: str
    model: str
    status: str  # ok | failed | skipped
    detail: str = ""
    ms: int = 0

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "status": self.status,
            "detail": self.detail,
            "ms": self.ms,
        }


@dataclass
class RouteEvent:
    type: str  # step | start | reasoning | delta | reset | done | exhausted
    text: str = ""
    step: Step | None = None
    candidate: Candidate | None = None
    steps: list[Step] = field(default_factory=list)


async def route(system: str, history: list[dict], image: str | None) -> AsyncIterator[RouteEvent]:
    """Yield deltas from the first candidate that answers; report every attempt as a step."""
    steps: list[Step] = []
    chain = providers.candidates(vision=image is not None)
    if not chain:
        yield RouteEvent(
            "exhausted",
            text="No AI provider is configured. Add GROQ_API_KEY, "
            "GEMINI_API_KEY or OLLAMA_BASE_URL to backend/.env.",
        )
        return
    # Candidates in cooldown go last instead of being dropped, so a fully cooled-down
    # chain still gets one real attempt.
    for candidate in chain:
        if cooldowns.blocked(candidate) > 0:
            await _recovered(candidate)
    ready = [c for c in chain if cooldowns.blocked(c) <= 0]
    waiting = [c for c in chain if cooldowns.blocked(c) > 0]
    for candidate in waiting:
        step = Step(
            candidate.provider,
            candidate.model,
            "skipped",
            f"cooling down ({int(cooldowns.blocked(candidate))}s)",
        )
        steps.append(step)
        yield RouteEvent("step", step=step)
    for candidate in ready + waiting:
        started = time.monotonic()
        produced = answered = False
        yield RouteEvent("start", candidate=candidate)
        try:
            async for piece in _pieces(candidate, system, history, image):
                kind, text = piece if isinstance(piece, tuple) else (providers.TEXT, piece)
                if not text:
                    continue
                produced = True
                if kind == providers.REASONING:
                    yield RouteEvent("reasoning", text=text)
                else:
                    answered = answered or bool(text.strip())
                    yield RouteEvent("delta", text=text)
            if not answered:
                raise ProviderFailure("empty", "Empty answer")
        except ProviderFailure as failure:
            cooldowns.penalize(candidate, failure)
            step = Step(
                candidate.provider,
                candidate.model,
                "failed",
                str(failure)
                if failure.kind == "timeout"
                else FRIENDLY.get(failure.kind, str(failure)),
                int((time.monotonic() - started) * 1000),
            )
            steps.append(step)
            yield RouteEvent("step", step=step)
            if produced:
                yield RouteEvent("reset")  # discard the partial answer before switching
            continue
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - unknown adapter bug: treat as unavailable
            failure = ProviderFailure("unavailable", "unexpected provider error")
            cooldowns.penalize(candidate, failure)
            step = Step(
                candidate.provider,
                candidate.model,
                "failed",
                FRIENDLY["unavailable"],
                int((time.monotonic() - started) * 1000),
            )
            steps.append(step)
            yield RouteEvent("step", step=step)
            if produced:
                yield RouteEvent("reset")
            continue
        step = Step(
            candidate.provider,
            candidate.model,
            "ok",
            "answered",
            int((time.monotonic() - started) * 1000),
        )
        steps.append(step)
        yield RouteEvent("step", step=step)
        yield RouteEvent("done", candidate=candidate, steps=steps)
        return
    yield RouteEvent(
        "exhausted",
        text="All configured AI providers are unavailable right now (rate limits or errors). "
        "Please try again in a minute.",
        steps=steps,
    )
