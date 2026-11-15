"""Automatic LLM fallback: try each provider/model in order, skip the ones cooling down.

A rate limit, timeout, outage or bad key moves the request to the next candidate
without any user action. Failed candidates are skipped for a while so the next
message does not wait on a provider that just failed.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from threading import Lock

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
        self._until: dict[str, float] = {}
        self._lock = Lock()

    @staticmethod
    def _keys(candidate: Candidate) -> tuple[str, str]:
        return candidate.provider, f"{candidate.provider}:{candidate.model}"

    def blocked(self, candidate: Candidate) -> float:
        now = time.monotonic()
        with self._lock:
            return max((self._until.get(key, 0) - now for key in self._keys(candidate)), default=0)

    def penalize(self, candidate: Candidate, failure: ProviderFailure) -> None:
        seconds = failure.retry_after or COOLDOWN_SECONDS.get(failure.kind, 30)
        if seconds <= 0:
            return
        provider_key, model_key = self._keys(candidate)
        # Keys and quota are per provider; a missing model or overload is per model.
        key = provider_key if failure.kind in ("auth",) else model_key
        with self._lock:
            self._until[key] = time.monotonic() + min(seconds, 3600)

    def clear(self) -> None:
        with self._lock:
            self._until.clear()

    def snapshot(self) -> dict[str, int]:
        now = time.monotonic()
        with self._lock:
            return {k: int(v - now) for k, v in self._until.items() if v > now}


cooldowns = Cooldowns()


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
    type: str  # step | start | delta | reset | done | exhausted
    text: str = ""
    step: Step | None = None
    candidate: Candidate | None = None
    steps: list[Step] = field(default_factory=list)


async def route(system: str, history: list[dict], image: str | None) -> AsyncIterator[RouteEvent]:
    """Yield deltas from the first candidate that answers; report every attempt as a step."""
    steps: list[Step] = []
    chain = providers.candidates()
    if not chain:
        yield RouteEvent(
            "exhausted",
            text="No AI provider is configured. Add GROQ_API_KEY, "
            "GEMINI_API_KEY or OLLAMA_BASE_URL to backend/.env.",
        )
        return
    # Candidates in cooldown go last instead of being dropped, so a fully cooled-down
    # chain still gets one real attempt.
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
        produced = False
        yield RouteEvent("start", candidate=candidate)
        try:
            async for delta in providers.ADAPTERS[candidate.provider](
                candidate.model, system, history, image
            ):
                produced = True
                yield RouteEvent("delta", text=delta)
            if not produced:
                raise ProviderFailure("empty", "Empty answer")
        except ProviderFailure as failure:
            cooldowns.penalize(candidate, failure)
            step = Step(
                candidate.provider,
                candidate.model,
                "failed",
                FRIENDLY.get(failure.kind, str(failure)),
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
