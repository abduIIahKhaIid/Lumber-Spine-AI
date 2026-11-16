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
            providers,
            "candidates",
            lambda vision=False: [Candidate(name, f"{name}-model") for name in adapters],
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
        # Image sizes are kept for coordinates; pixels never are.
        assert all(set(i) == {"index", "slice", "width", "height"} for i in stored["images"])


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


def test_image_messages_use_the_vision_chain(monkeypatch):
    from app.core import config

    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    monkeypatch.setenv("GROQ_VISION_MODELS", "")
    config.get_settings.cache_clear()
    text_chain = [(c.provider, c.model) for c in providers.candidates()]
    vision_chain = [(c.provider, c.model) for c in providers.candidates(vision=True)]
    assert text_chain[0] == ("groq", "qwen/qwen3.8-27b")
    assert vision_chain[0][0] == "gemini"
    assert ("groq", "qwen/qwen3.8-27b") in vision_chain  # same model reads images
    monkeypatch.setenv("GROQ_VISION_MODELS", "vision-only")
    config.get_settings.cache_clear()
    vision_chain = [(c.provider, c.model) for c in providers.candidates(vision=True)]
    assert ("groq", "vision-only") in vision_chain
    assert ("groq", "qwen/qwen3.8-27b") not in vision_chain


def test_result_preview_is_stored_but_never_sent_to_the_model(chain, sample_result):
    import base64
    from io import BytesIO

    from PIL import Image

    from app.services.chat.context import system_prompt

    buffer = BytesIO()
    Image.new("RGB", (900, 600), "gray").save(buffer, format="PNG")
    preview = base64.b64encode(buffer.getvalue()).decode()
    chain(groq=["ok"])
    with TestClient(create_app()) as client:
        thread = client.post(
            "/api/chat/threads",
            json={"case_context": sample_result, "preview_image": preview},
        ).json()
        stored = client.get(f"/api/chat/threads/{thread['id']}").json()["case_context"]
    shrunk = Image.open(BytesIO(base64.b64decode(stored["preview"])))
    assert max(shrunk.size) == 720 and shrunk.format == "JPEG"
    assert "preview" not in system_prompt("english", stored).split("Scan context")[1]
    assert stored["preview"][:20] not in system_prompt("english", stored)


def _png(size=(300, 200), colour="gray"):
    import base64
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_think_tags_are_split_across_chunks():
    from app.services.chat.providers import ThinkSplitter

    splitter = ThinkSplitter()
    pieces = []
    for chunk in ["<thi", "nk>Let me ", "check</th", "ink>\n\nThe answer", " is L4/L5."]:
        pieces += splitter.feed(chunk)
    pieces += splitter.flush()
    reasoning = "".join(t for k, t in pieces if k == "reasoning")
    text = "".join(t for k, t in pieces if k == "text")
    assert reasoning == "Let me check"
    assert text.strip() == "The answer is L4/L5."


def test_provider_parsers_return_reasoning_and_text():
    from app.services.chat.providers import _parse_groq, _parse_ollama

    groq = 'data: {"choices":[{"delta":{"reasoning":"hmm","content":""}}]}'
    assert _parse_groq(groq) == ("hmm", "")
    assert _parse_ollama('{"message":{"thinking":"","content":"Hi"}}') == ("", "Hi")


def test_reasoning_is_streamed_and_saved(chain):
    chain(groq=[("reasoning", "Thinking about it. "), ("reasoning", "Done."), "Answer"])
    with TestClient(create_app()) as client:
        tid = client.post("/api/chat/threads", json={}).json()["id"]
        events = sse(client.post(f"/api/chat/threads/{tid}/messages", json={"content": "q"}))
        types = [e["type"] for e in events]
        assert types.count("reasoning") == 2 and "reasoning_done" in types
        assert types.index("reasoning_done") < types.index("delta")
        saved = client.get(f"/api/chat/threads/{tid}").json()["messages"][1]
    assert saved["reasoning"] == "Thinking about it. Done."
    assert saved["content"] == "Answer" and "reasoning_seconds" in saved


def test_answer_without_reasoning_has_no_thinking(chain):
    chain(groq=["Plain answer"])
    with TestClient(create_app()) as client:
        tid = client.post("/api/chat/threads", json={}).json()["id"]
        events = sse(client.post(f"/api/chat/threads/{tid}/messages", json={"content": "q"}))
        saved = client.get(f"/api/chat/threads/{tid}").json()["messages"][1]
    assert not any(e["type"].startswith("reasoning") for e in events)
    assert saved["reasoning"] == "" and "reasoning_seconds" not in saved


def test_reasoning_only_answer_falls_back(chain):
    chain(groq=[("reasoning", "thinking but no answer")], gemini=["Real answer"])
    events = collect(route("s", [{"role": "user", "content": "q"}], None))
    assert events[-1].type == "done" and events[-1].candidate.provider == "gemini"


def test_asking_for_a_box_shows_the_matching_images(chain, sample_result):
    chain(groq=["Here is the L4/L5 box."])
    sample_result["images"] = [{"index": 0, "slice_number": 7, "annotated": _png()}]
    sample_result["findings"][1]["explanation"] = {
        "crop_image": _png((64, 64)),
        "heatmap_image": _png((64, 64), "red"),
        "method": "Grad-CAM",
    }
    from app.services.chat.tools import assets_from_result

    assets = assets_from_result(sample_result)
    with TestClient(create_app()) as client:
        tid = client.post(
            "/api/chat/threads", json={"case_context": sample_result, "assets": assets}
        ).json()["id"]
        plain = sse(client.post(f"/api/chat/threads/{tid}/messages", json={"content": "Why?"}))
        assert not any(e["type"] == "elements" for e in plain)
        events = sse(
            client.post(
                f"/api/chat/threads/{tid}/messages",
                json={"content": "L4-L5 ka box dikhao"},
            )
        )
        tool = next(e["tool"] for e in events if e["type"] == "tool")
        elements = next(e["elements"] for e in events if e["type"] == "elements")
        saved = client.get(f"/api/chat/threads/{tid}").json()["messages"][-1]
    assert tool["name"] == "show_images" and tool["status"] == "done"
    assert [e["key"] for e in elements] == ["slice:0", "focus:F2", "crop:F2"]
    assert saved["elements"][0]["data"] and saved["tools"][0]["name"] == "show_images"


def test_attached_scan_is_analysed_by_the_tool(chain, sample_result, monkeypatch):
    from app.jobs import runner

    sample_result["images"] = [{"index": 0, "slice_number": 3, "annotated": _png()}]

    def fake(kind, path, progress, submitted_at=None):
        from pathlib import Path

        Path(path).unlink()  # the real runner deletes uploads too
        progress(40, "Stage 1: locating spinal levels in 3D")
        return {**sample_result, "timings": {"model_seconds": 1.0, "queue_seconds": 0.1}}

    monkeypatch.setattr(runner, "analyze_upload", fake)
    chain(groq=["The scan shows a severe L4/L5 finding."])
    with TestClient(create_app()) as client:
        tid = client.post("/api/chat/threads", json={}).json()["id"]
        attached = client.post(
            f"/api/chat/threads/{tid}/attachments",
            files=[("files", ("scan.zip", b"PK-not-really", "application/zip"))],
        ).json()
        assert attached["kind"] == "multi" and attached["name"] == "scan.zip"
        events = sse(
            client.post(
                f"/api/chat/threads/{tid}/messages",
                json={"content": "", "attachment": {"id": attached["id"], "name": "scan.zip"}},
            )
        )
        tool_events = [e["tool"] for e in events if e["type"] == "tool"]
        assert tool_events[0]["name"] == "analyze_scan"
        done = [t for t in tool_events if t["name"] == "analyze_scan"][-1]
        assert done["status"] == "done" and "1 severe" in done["message"]
        assert any(e["type"] == "case" for e in events)
        assert any(e["type"] == "elements" for e in events)
        thread = client.get(f"/api/chat/threads/{tid}").json()
        expired = client.post(
            f"/api/chat/threads/{tid}/messages",
            json={"content": "", "attachment": {"id": attached["id"], "name": "scan.zip"}},
        )
    assert thread["case_context"]["condition"] == "Spinal canal stenosis"
    assert thread["messages"][0]["attachment"] == {"name": "scan.zip", "kind": "multi"}
    assert thread["messages"][1]["tools"][0]["status"] == "done"
    assert expired.status_code == 410


def test_level_mentions_are_parsed():
    from app.services.chat.tools import mentioned, wants_images

    assert mentioned("show the left L4/L5 box") == ({"L4/L5"}, "left")
    assert mentioned("L5-S1 aur L3 L4") == ({"L5/S1", "L3/L4"}, None)
    assert wants_images("L4/L5 ki tasveer dikhao") and not wants_images("what is stenosis?")
    assert wants_images("show me the box of the worst level")
    assert not wants_images("tell me the coordinate of the spinal level of the previous image")


def test_coordinates_reach_the_model(sample_result):
    from app.services.chat.context import clean_case, system_prompt

    sample_result["images"] = [{"index": 0, "slice_number": 9, "width": 384, "height": 384}]
    case = clean_case(sample_result)
    finding = case["findings"][0]
    assert finding["box"] == [10, 10, 40, 40] and finding["center"] == [25, 25]
    assert case["images"] == [{"index": 0, "slice": 9, "width": 384, "height": 384}]
    prompt = system_prompt("english", case)
    assert '"box":[10,10,40,40]' in prompt and "pixel coordinates" in prompt


def slow_adapter(words, delay=0.05):
    async def adapter(model, system, history, image):
        for word in words:
            await asyncio.sleep(delay)
            yield word

    return adapter


def _wait_for(check, timeout=10.0):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("timed out")


def test_answer_keeps_running_after_the_viewer_disconnects(monkeypatch):
    monkeypatch.setattr(providers, "ADAPTERS", {"groq": slow_adapter(["a ", "b ", "c ", "done"])})
    monkeypatch.setattr(providers, "candidates", lambda vision=False: [Candidate("groq", "m")])
    with TestClient(create_app()) as client:
        tid = client.post("/api/chat/threads", json={}).json()["id"]
        with client.stream(
            "POST", f"/api/chat/threads/{tid}/messages", json={"content": "q"}
        ) as response:
            next(response.iter_lines())  # read one event, then leave
        assert client.get(f"/api/chat/threads/{tid}").json()["running"] is True
        assert any(t["running"] for t in client.get("/api/chat/threads").json())
        # Re-attaching replays the answer from the start.
        replay = sse(client.get(f"/api/chat/threads/{tid}/stream"))
        assert replay[0]["type"] == "user_message" and replay[-1]["type"] == "done"
        thread = _wait_for(
            lambda: (t := client.get(f"/api/chat/threads/{tid}").json())["running"] is False and t
        )
    assert thread["messages"][-1]["content"] == "a b c done"
    assert thread["messages"][-1]["status"] == "complete"


def test_stop_ends_the_run_and_keeps_the_partial_answer(monkeypatch):
    monkeypatch.setattr(
        providers, "ADAPTERS", {"groq": slow_adapter(["first "] + ["more "] * 50, 0.05)}
    )
    monkeypatch.setattr(providers, "candidates", lambda vision=False: [Candidate("groq", "m")])
    with TestClient(create_app()) as client:
        tid = client.post("/api/chat/threads", json={}).json()["id"]
        with client.stream(
            "POST", f"/api/chat/threads/{tid}/messages", json={"content": "q"}
        ) as response:
            for line in response.iter_lines():
                if '"delta"' in line:
                    break
        busy = client.post(f"/api/chat/threads/{tid}/messages", json={"content": "again"})
        assert busy.status_code == 409
        assert client.post(f"/api/chat/threads/{tid}/stop").json() == {"stopped": True}
        thread = client.get(f"/api/chat/threads/{tid}").json()
    assert thread["running"] is False
    assert thread["messages"][-1]["status"] == "stopped"
    assert thread["messages"][-1]["content"].startswith("first")


def test_ollama_missing_model_cools_down_briefly(chain):
    from app.services.chat.router import cooldowns

    ollama, groq = Candidate("ollama", "qwen3-vl:8b-thinking"), Candidate("groq", "m")
    cooldowns.penalize(ollama, ProviderFailure("not_found", "404"))
    cooldowns.penalize(groq, ProviderFailure("not_found", "404"))
    assert 50 < cooldowns.blocked(ollama) <= 60
    assert cooldowns.blocked(groq) > 3000
    cooldowns.penalize(ollama, ProviderFailure("auth", "403"))
    assert cooldowns.reason(ollama) in {"auth", "not_found"} and cooldowns.blocked(ollama) <= 60


def test_cooling_ollama_is_retried_once_the_model_is_back(monkeypatch):
    from app.services.chat.router import cooldowns

    calls = []

    async def ollama(model, system, history, image):
        calls.append(model)
        yield "from ollama"

    async def has_model(model):
        return True

    monkeypatch.setattr(providers, "ADAPTERS", {"ollama": ollama})
    monkeypatch.setattr(providers, "candidates", lambda vision=False: [Candidate("ollama", "q")])
    monkeypatch.setattr(providers, "ollama_has_model", has_model)
    cooldowns.penalize(Candidate("ollama", "q"), ProviderFailure("not_found", "404"))
    events = collect(route("s", [{"role": "user", "content": "q"}], None))
    assert calls == ["q"]
    assert not any(e.type == "step" and e.step.status == "skipped" for e in events)
    assert cooldowns.blocked(Candidate("ollama", "q")) == 0


def test_cooling_ollama_stays_skipped_while_the_model_is_missing(monkeypatch):
    from app.services.chat.router import cooldowns

    async def has_model(model):
        return False

    monkeypatch.setattr(providers, "ollama_has_model", has_model)
    monkeypatch.setattr(
        providers,
        "candidates",
        lambda vision=False: [Candidate("ollama", "q"), Candidate("groq", "m")],
    )

    async def groq(model, system, history, image):
        yield "from groq"

    monkeypatch.setattr(providers, "ADAPTERS", {"groq": groq, "ollama": groq})
    cooldowns.penalize(Candidate("ollama", "q"), ProviderFailure("not_found", "404"))
    events = collect(route("s", [{"role": "user", "content": "q"}], None))
    skipped = [e.step for e in events if e.type == "step" and e.step.status == "skipped"]
    assert [s.provider for s in skipped] == ["ollama"]
    assert events[-1].candidate.provider == "groq"


def test_ollama_tags_check(monkeypatch):
    import httpx

    from app.core.config import get_settings

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.test")
    get_settings.cache_clear()
    hits = []

    def handler(request):
        hits.append(request.url.path)
        return httpx.Response(
            200, json={"models": [{"name": "qwen3-vl:8b-thinking"}, {"name": "gemma3:latest"}]}
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    assert asyncio.run(providers.ollama_has_model("qwen3-vl:8b-thinking"))
    assert asyncio.run(providers.ollama_has_model("gemma3"))  # "gemma3" means gemma3:latest
    assert not asyncio.run(providers.ollama_has_model("llama3"))
    assert hits == ["/api/tags"]  # cached for a few seconds
    get_settings.cache_clear()


def test_cooldowns_can_be_cleared_without_a_restart():
    from app.services.chat.router import cooldowns

    cooldowns.penalize(Candidate("groq", "m"), ProviderFailure("not_found", "404"))
    with TestClient(create_app()) as client:
        assert client.get("/api/chat/providers").json()["cooldowns"]
        assert client.delete("/api/chat/providers/cooldowns").json() == {"cooldowns": {}}


def _timeout_chain(monkeypatch, first):
    from app.core.config import get_settings

    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "1")
    get_settings.cache_clear()

    async def groq(model, system, history, image):
        yield "from groq"

    monkeypatch.setattr(providers, "ADAPTERS", {"ollama": first, "groq": groq})
    monkeypatch.setattr(
        providers,
        "candidates",
        lambda vision=False: [Candidate("ollama", "slow"), Candidate("groq", "m")],
    )


def test_a_model_that_does_not_answer_in_time_is_replaced(monkeypatch):
    import time

    async def silent(model, system, history, image):
        await asyncio.sleep(30)
        yield "too late"

    _timeout_chain(monkeypatch, silent)
    started = time.monotonic()
    events = collect(route("s", [{"role": "user", "content": "q"}], None))
    failed = [e.step for e in events if e.type == "step" and e.step.status == "failed"]
    assert time.monotonic() - started < 5
    assert failed[0].provider == "ollama" and failed[0].detail == "no response in 1 s"
    assert events[-1].type == "done" and events[-1].candidate.provider == "groq"
    assert "".join(e.text for e in events if e.type == "delta") == "from groq"


def test_a_model_that_stalls_mid_answer_is_replaced(monkeypatch):
    async def stalls(model, system, history, image):
        yield "partial "
        await asyncio.sleep(30)
        yield "never"

    _timeout_chain(monkeypatch, stalls)
    events = collect(route("s", [{"role": "user", "content": "q"}], None))
    types = [e.type for e in events]
    assert "reset" in types and events[-1].candidate.provider == "groq"
    text = "".join(e.text for e in events[types.index("reset") :] if e.type == "delta")
    assert text == "from groq"
