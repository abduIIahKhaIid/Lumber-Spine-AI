"""Conversation orchestration: send, edit-and-resend and regenerate, streamed as events."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

from app.services.chat import store, tools
from app.services.chat.context import system_prompt
from app.services.chat.providers import PROVIDER_NAMES
from app.services.chat.router import route

DEFAULT_TITLE = "New chat"


def title_from(text: str) -> str:
    line = " ".join(text.split())
    return (line[:57] + "…") if len(line) > 58 else (line or DEFAULT_TITLE)


def _shown_note(elements: list[dict], analysed: bool) -> str:
    if not elements and not analysed:
        return ""
    lines = ["", "## Shown in this reply"]
    if analysed:
        lines.append(
            "The app has just run the SpineScope models on the scan the user attached; the scan "
            "context above is that new result. Summarise it for the user."
        )
    if elements:
        lines.append(
            "The app is displaying these images under your answer, so do not say you cannot "
            "show images; refer to them briefly and explain what the boxes and colours mean:"
        )
        lines += [f"- {item['caption']}" for item in elements]
    return "\n".join(lines)


async def _tools(thread: dict, text: str, attachment: dict | None, extras: dict, force: bool):
    """Runs the app-side tools for this turn; yields events and fills `extras`."""
    analysed = False
    if attachment and tools.attachment_path(attachment.get("id", "")):
        async for event in tools.analyze_scan(thread, attachment):
            if event["type"] == "result":
                tools.adopt_result(thread, event["result"])
                yield {"type": "case", "case": thread["case_context"]}
                analysed = True
            else:
                _remember_tool(extras, event["tool"])
                if event["tool"]["status"] == "error":
                    extras["_failed"] = event["tool"]["message"]
                yield event
    elements = await asyncio.to_thread(
        tools.images_for,
        thread["id"],
        thread.get("case_context"),
        text,
        analysed or bool(attachment),
    )
    if elements:
        noun = "images" if len(elements) > 1 else "image"
        tool = {
            "id": "show-" + elements[0]["key"].replace(":", "-"),
            "name": "show_images",
            "label": f"Showing {len(elements)} {noun} from the scan",
            "status": "done",
            "progress": 100,
            "message": ", ".join(item["caption"] for item in elements),
        }
        _remember_tool(extras, tool)
        extras["elements"] = [
            {"type": "image", "key": e["key"], "caption": e["caption"], "data": e["image"]}
            for e in elements
        ]
        yield {"type": "tool", "tool": tool}
        yield {"type": "elements", "elements": extras["elements"]}
    extras["_note"] = _shown_note(elements, analysed)
    if extras.get("_failed"):
        extras["_note"] += (
            "\n\n## Scan analysis failed\nThe SpineScope analysis of the file the user just "
            f"attached failed: {extras['_failed']} Tell the user this briefly and what to try; "
            "do not describe findings for that file."
        )


def _remember_tool(extras: dict, tool: dict) -> None:
    tool = {k: v for k, v in tool.items() if k != "preview"}  # only shown while it runs
    tools_list = extras.setdefault("tools", [])
    for index, item in enumerate(tools_list):
        if item["id"] == tool["id"]:
            tools_list[index] = tool
            return
    tools_list.append(tool)


def _saved_extras(extras: dict, reasoning_seconds: float | None) -> dict:
    kept = {k: v for k, v in extras.items() if not k.startswith("_") and v}
    if reasoning_seconds is not None:
        kept["reasoning_seconds"] = round(reasoning_seconds, 1)
    return kept


async def _generate(
    thread: dict,
    image: str | None,
    text_in: str = "",
    attachment: dict | None = None,
    force_images: bool = False,
) -> AsyncIterator[dict]:
    thread_id = thread["id"]
    text, reasoning, steps, candidate = "", "", [], None
    extras: dict = {}
    reasoning_started = reasoning_seconds = None
    finished = False
    yield {"type": "thinking"}
    try:
        async for event in _tools(thread, text_in, attachment, extras, force_images):
            yield event
        turns = store.history(thread_id)
        prompt = system_prompt(thread.get("language", "english"), thread.get("case_context"))
        prompt += extras.get("_note", "")
        async for event in route(prompt, turns, image):
            if event.type == "step":
                steps.append(event.step.as_dict())
                yield {"type": "step", "step": event.step.as_dict()}
            elif event.type == "start":
                candidate = event.candidate
                yield {
                    "type": "provider",
                    "provider": candidate.provider,
                    "provider_name": PROVIDER_NAMES[candidate.provider],
                    "model": candidate.model,
                }
            elif event.type == "reasoning":
                if reasoning_started is None:
                    reasoning_started = time.monotonic()
                reasoning += event.text
                yield {"type": "reasoning", "text": event.text}
            elif event.type == "delta":
                if reasoning_started is not None and reasoning_seconds is None:
                    reasoning_seconds = time.monotonic() - reasoning_started
                    yield {"type": "reasoning_done", "seconds": round(reasoning_seconds, 1)}
                text += event.text
                yield {"type": "delta", "text": event.text}
            elif event.type == "reset":
                text, reasoning = "", ""
                reasoning_started = reasoning_seconds = None
                yield {"type": "reset"}
            elif event.type == "done":
                message = store.add_message(
                    thread_id,
                    "assistant",
                    text.strip(),
                    provider=candidate.provider,
                    model=candidate.model,
                    steps=steps,
                    reasoning=reasoning.strip(),
                    extras=_saved_extras(extras, reasoning_seconds),
                )
                finished = True
                yield {"type": "assistant_message", "message": message}
            elif event.type == "exhausted":
                message = store.add_message(
                    thread_id,
                    "assistant",
                    event.text,
                    status="error",
                    steps=steps,
                    extras=_saved_extras(extras, None),
                )
                finished = True
                yield {"type": "error", "message": event.text, "assistant_message": message}
    except (asyncio.CancelledError, GeneratorExit):
        if not finished and (text or extras.get("elements")):
            store.add_message(
                thread_id,
                "assistant",
                text,
                provider=candidate.provider if candidate else None,
                model=candidate.model if candidate else None,
                status="stopped",
                steps=steps,
                reasoning=reasoning.strip(),
                extras=_saved_extras(extras, reasoning_seconds),
            )
        raise
    yield {"type": "done"}


async def send(
    thread: dict, content: str, image: str | None, attachment: dict | None = None
) -> AsyncIterator[dict]:
    extras = (
        {"attachment": {"name": attachment["name"], "kind": attachment["kind"]}}
        if attachment
        else None
    )
    message = store.add_message(thread["id"], "user", content, image=image, extras=extras)
    yield {"type": "user_message", "message": message}
    if thread["title"] == DEFAULT_TITLE:
        updated = store.update_thread(thread["id"], title=title_from(content))
        yield {"type": "title", "title": updated["title"]}
    async for event in _generate(thread, image, content, attachment):
        yield event


async def edit(thread: dict, message_id: str, content: str) -> AsyncIterator[dict]:
    message = store.edit_and_truncate(thread["id"], message_id, content)
    if message is None:
        yield {"type": "error", "message": "That message can no longer be edited."}
        return
    yield {"type": "user_message", "message": message, "replaces": message_id}
    async for event in _generate(
        thread, message.get("image"), content, force_images=bool(message.get("attachment"))
    ):
        yield event


async def regenerate(thread: dict) -> AsyncIterator[dict]:
    message = store.truncate_after_last_user(thread["id"])
    if message is None:
        yield {"type": "error", "message": "There is no question to answer again."}
        return
    yield {"type": "truncated", "after": message["id"]}
    attached = bool(message.get("attachment"))
    async for event in _generate(
        thread, message.get("image"), message["content"], force_images=attached
    ):
        yield event
