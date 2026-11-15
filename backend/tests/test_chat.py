"""Assistant: automatic provider fallback, cooldowns, threads, edit-and-resend."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.chat import providers
from app.services.chat.providers import Candidate, ProviderFailure
from app.services.chat.router import cooldowns, route


def fake_adapter(behaviour):
    """behaviour: list of str deltas, or a ProviderFailure (optionally after deltas)."""

    async def adapter(model, system, history, image):
        for item in behaviour:
            if isinstance(item, ProviderFailure):
                raise item
            yield item

    return adapter


@pytest.fixture
def chain(monkeypatch):
    def install(**adapters):
        monkeypatch.setattr(
            providers, "ADAPTERS", {k: fake_adapter(v) for k, v in adapters.items()}
        )
        monkeypatch.setattr(
            providers, "candidates", lambda: [Candidate(name, f"{name}-model") for name in adapters]
        )

    return install


def collect(events):
    async def run():
        return [event async for event in events]

    return asyncio.run(run())


def test_rate_limit_falls_back_to_next_provider(chain):
    chain(groq=[ProviderFailure("rate_limit", "429")], gemini=["Hello", " there"])
    events = collect(route("system", [{"role": "user", "content": "hi"}], None))
    kinds = [e.type for e in events]
    assert kinds.count("delta") == 2
    failed = [e.step for e in events if e.type == "step" and e.step.status == "failed"]
    assert failed[0].provider == "groq" and failed[0].detail == "rate limit reached"
    assert events[-1].type == "done" and events[-1].candidate.provider == "gemini"
    assert cooldowns.blocked(Candidate("groq", "groq-model")) > 0


def test_partial_answer_is_reset_before_switching(chain):
    chain(groq=["half", ProviderFailure("unavailable", "500")], ollama=["full answer"])
    kinds = [e.type for e in collect(route("s", [{"role": "user", "content": "q"}], None))]
    assert kinds.index("reset") < len(kinds) - 1
    assert kinds[-1] == "done"


def test_cooling_provider_is_tried_last(chain):
    chain(groq=["from groq"], gemini=["from gemini"])
    cooldowns.penalize(Candidate("groq", "groq-model"), ProviderFailure("rate_limit", "x"))
    events = collect(route("s", [{"role": "user", "content": "q"}], None))
    assert events[0].type == "step" and events[0].step.status == "skipped"
    assert events[-1].candidate.provider == "gemini"


def test_all_providers_failing_is_reported(chain):
    chain(groq=[ProviderFailure("auth", "401")], gemini=[ProviderFailure("timeout", "t")])
    events = collect(route("s", [{"role": "user", "content": "q"}], None))
    assert events[-1].type == "exhausted"


def sse(response):
    return [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]


def test_thread_lifecycle_edit_and_regenerate(chain):
    chain(groq=["Answer"])
    with TestClient(create_app()) as client:
        thread = client.post("/api/chat/threads", json={}).json()
        tid = thread["id"]
        events = sse(
            client.post(f"/api/chat/threads/{tid}/messages", json={"content": "What is SCS?"})
        )
        types = [e["type"] for e in events]
        assert types[0] == "user_message" and "title" in types and types[-1] == "done"
        assert any(e["type"] == "provider" and e["provider"] == "groq" for e in events)

        detail = client.get(f"/api/chat/threads/{tid}").json()
        assert detail["title"] == "What is SCS?"
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
        assert detail["messages"][1]["provider"] == "groq"

        # A second turn, then edit the first question: later turns are discarded.
        sse(client.post(f"/api/chat/threads/{tid}/messages", json={"content": "And NFN?"}))
        first = detail["messages"][0]["id"]
        edited = sse(
            client.post(
                f"/api/chat/threads/{tid}/messages/{first}/edit", json={"content": "Explain SS"}
            )
        )
        assert edited[0]["type"] == "user_message" and edited[0]["message"]["edited"] is True
        messages = client.get(f"/api/chat/threads/{tid}").json()["messages"]
        assert [m["content"] for m in messages] == ["Explain SS", "Answer"]

        regenerated = sse(client.post(f"/api/chat/threads/{tid}/regenerate"))
        assert regenerated[0]["type"] == "truncated"
        assert len(client.get(f"/api/chat/threads/{tid}").json()["messages"]) == 2

        listed = client.get("/api/chat/threads", params={"q": "explain"}).json()
        assert [t["id"] for t in listed] == [tid]
        assert (
            client.patch(f"/api/chat/threads/{tid}", json={"title": "Renamed"}).json()["title"]
            == "Renamed"
        )
        assert client.delete(f"/api/chat/threads/{tid}").status_code == 204
        assert client.get(f"/api/chat/threads/{tid}").status_code == 404


def test_case_context_is_sanitised(chain, sample_result):
    chain(groq=["ok"])
    with TestClient(create_app()) as client:
        thread = client.post(
            "/api/chat/threads", json={"case_context": {**sample_result, "patient": "Jane Doe"}}
        ).json()
        stored = client.get(f"/api/chat/threads/{thread['id']}").json()["case_context"]
        assert "patient" not in stored and stored["findings"][1]["id"] == "F2"
        assert "images" not in stored


def test_empty_message_rejected_and_no_provider_configured():
    with TestClient(create_app()) as client:
        tid = client.post("/api/chat/threads", json={}).json()["id"]
        assert (
            client.post(f"/api/chat/threads/{tid}/messages", json={"content": " "}).status_code
            == 400
        )
        events = sse(client.post(f"/api/chat/threads/{tid}/messages", json={"content": "hi"}))
        assert any(e["type"] == "error" for e in events)
        assert client.get("/api/chat/providers").json()["chain"] == []
