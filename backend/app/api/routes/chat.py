"""Assistant API: threads, streamed answers, edit-and-resend, regenerate."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.security import rate_limited
from app.services.chat import providers, service, store
from app.services.chat.context import ChatInputError, clean_case, prepare_image
from app.services.chat.router import cooldowns

router = APIRouter(prefix="/api/chat", tags=["assistant"])
Language = Literal["english", "urdu"]


class ThreadCreate(BaseModel):
    title: str = Field(default=service.DEFAULT_TITLE, max_length=120)
    language: Language = "english"
    case_context: dict | None = None
    # Small annotated slice shown on the attached-result card (never sent to the model).
    preview_image: str | None = Field(default=None, max_length=3_000_000)


class ThreadUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    language: Language | None = None


class MessageCreate(BaseModel):
    content: str = Field(default="", max_length=8000)
    image: str | None = Field(default=None, max_length=14_000_000)


class MessageEdit(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


def _sse(events: AsyncIterator[dict]) -> StreamingResponse:
    async def body():
        async for event in events:
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


def _thread_or_404(thread_id: str) -> dict:
    thread = store.get_thread(thread_id, with_messages=False)
    if thread is None:
        raise HTTPException(404, "Conversation not found")
    return thread


@router.get("/providers")
def provider_status():
    chain = providers.candidates()
    return {
        "configured": {name: providers.configured(name) for name in providers.ADAPTERS},
        "chain": [{"provider": c.provider, "model": c.model, "label": c.label} for c in chain],
        "cooldowns": cooldowns.snapshot(),
    }


@router.get("/threads")
def list_threads(q: str = Query(default="", max_length=100)):
    return store.list_threads(q.strip())


@router.post("/threads", status_code=201)
def create_thread(body: ThreadCreate):
    case = clean_case(body.case_context)
    if case and body.preview_image:
        try:
            case["preview"] = prepare_image(body.preview_image, max_side=720)
        except ChatInputError as exc:
            raise HTTPException(400, str(exc)) from exc
    return store.create_thread(body.title.strip() or service.DEFAULT_TITLE, body.language, case)


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str):
    thread = store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(404, "Conversation not found")
    return thread


@router.patch("/threads/{thread_id}")
def update_thread(thread_id: str, body: ThreadUpdate):
    _thread_or_404(thread_id)
    return store.update_thread(thread_id, title=body.title, language=body.language)


@router.delete("/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: str):
    if not store.delete_thread(thread_id):
        raise HTTPException(404, "Conversation not found")


@router.post("/threads/{thread_id}/messages", dependencies=[Depends(rate_limited("chat"))])
def send_message(thread_id: str, body: MessageCreate):
    thread = _thread_or_404(thread_id)
    content = body.content.strip()
    try:
        image = prepare_image(body.image)
    except ChatInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not content and not image:
        raise HTTPException(400, "Write a message or attach an image.")
    return _sse(service.send(thread, content or "Please explain the attached image.", image))


@router.post(
    "/threads/{thread_id}/messages/{message_id}/edit",
    dependencies=[Depends(rate_limited("chat"))],
)
def edit_message(thread_id: str, message_id: str, body: MessageEdit):
    _thread_or_404(thread_id)
    if store.get_message(thread_id, message_id) is None:
        raise HTTPException(404, "Message not found")
    return _sse(service.edit(store.get_thread(thread_id), message_id, body.content.strip()))


@router.post("/threads/{thread_id}/regenerate", dependencies=[Depends(rate_limited("chat"))])
def regenerate(thread_id: str):
    _thread_or_404(thread_id)
    return _sse(service.regenerate(store.get_thread(thread_id)))
