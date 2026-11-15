"""Conversation orchestration: send, edit-and-resend and regenerate, streamed as events."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.services.chat import store
from app.services.chat.context import system_prompt
from app.services.chat.providers import PROVIDER_NAMES
from app.services.chat.router import route

DEFAULT_TITLE = "New chat"


def title_from(text: str) -> str:
    line = " ".join(text.split())
    return (line[:57] + "…") if len(line) > 58 else (line or DEFAULT_TITLE)


async def _generate(thread: dict, image: str | None) -> AsyncIterator[dict]:
    thread_id = thread["id"]
    turns = store.history(thread_id)
    prompt = system_prompt(thread.get("language", "english"), thread.get("case_context"))
    text, steps, candidate = "", [], None
    finished = False
    yield {"type": "thinking"}
    try:
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
            elif event.type == "delta":
                text += event.text
                yield {"type": "delta", "text": event.text}
            elif event.type == "reset":
                text = ""
                yield {"type": "reset"}
            elif event.type == "done":
                message = store.add_message(
                    thread_id,
                    "assistant",
                    text,
                    provider=candidate.provider,
                    model=candidate.model,
                    steps=steps,
                )
                finished = True
                yield {"type": "assistant_message", "message": message}
            elif event.type == "exhausted":
                message = store.add_message(
                    thread_id, "assistant", event.text, status="error", steps=steps
                )
                finished = True
                yield {"type": "error", "message": event.text, "assistant_message": message}
    except (asyncio.CancelledError, GeneratorExit):
        if not finished and text:
            store.add_message(
                thread_id,
                "assistant",
                text,
                provider=candidate.provider if candidate else None,
                model=candidate.model if candidate else None,
                status="stopped",
                steps=steps,
            )
        raise
    yield {"type": "done"}


async def send(thread: dict, content: str, image: str | None) -> AsyncIterator[dict]:
    message = store.add_message(thread["id"], "user", content, image=image)
    yield {"type": "user_message", "message": message}
    if thread["title"] == DEFAULT_TITLE:
        updated = store.update_thread(thread["id"], title=title_from(content))
        yield {"type": "title", "title": updated["title"]}
    async for event in _generate(thread, image):
        yield event


async def edit(thread: dict, message_id: str, content: str) -> AsyncIterator[dict]:
    message = store.edit_and_truncate(thread["id"], message_id, content)
    if message is None:
        yield {"type": "error", "message": "That message can no longer be edited."}
        return
    yield {"type": "user_message", "message": message, "replaces": message_id}
    async for event in _generate(thread, message.get("image")):
        yield event


async def regenerate(thread: dict) -> AsyncIterator[dict]:
    message = store.truncate_after_last_user(thread["id"])
    if message is None:
        yield {"type": "error", "message": "There is no question to answer again."}
        return
    yield {"type": "truncated", "after": message["id"]}
    async for event in _generate(thread, message.get("image")):
        yield event
