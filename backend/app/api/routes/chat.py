"""Assistant API: threads, streamed answers, edit-and-resend, regenerate."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.routes.scans import _save_upload
from app.core.security import rate_limited
from app.services.chat import providers, service, store, tools
from app.services.chat.context import ChatInputError, clean_case, prepare_image
from app.services.chat.router import cooldowns
from app.services.chat.runs import RunBusy, runs

router = APIRouter(prefix="/api/chat", tags=["assistant"])
Language = Literal["english", "urdu"]


class Asset(BaseModel):
    key: str = Field(max_length=24)
    caption: str = Field(default="", max_length=120)
    image: str = Field(max_length=4_000_000)


class ThreadCreate(BaseModel):
    title: str = Field(default=service.DEFAULT_TITLE, max_length=120)
    language: Language = "english"
    case_context: dict | None = None
    # Small annotated slice shown on the attached-result card (never sent to the model).
    preview_image: str | None = Field(default=None, max_length=3_000_000)
    # Annotated slices, model crops and focus maps the assistant can show on request.
    assets: list[Asset] = Field(default_factory=list, max_length=60)


class ThreadUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    language: Language | None = None


class Attachment(BaseModel):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    name: str = Field(default="scan", max_length=120)


class MessageCreate(BaseModel):
    content: str = Field(default="", max_length=8000)
    image: str | None = Field(default=None, max_length=14_000_000)
    attachment: Attachment | None = None


class MessageEdit(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


def _start(thread_id: str, events: AsyncIterator[dict]) -> StreamingResponse:
    """Run the answer as a background task and stream it; disconnecting does not stop it."""
    try:
        run = runs.start(thread_id, events)
    except RunBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    return _sse(run.follow())


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


@router.delete("/providers/cooldowns", dependencies=[Depends(rate_limited("chat"))])
def clear_cooldowns():
    """Retry every provider on the next message (e.g. after `ollama pull`), no restart needed."""
    cooldowns.clear()
    return {"cooldowns": cooldowns.snapshot()}


@router.get("/threads")
def list_threads(q: str = Query(default="", max_length=100)):
    running = runs.running_ids()
    return [{**t, "running": t["id"] in running} for t in store.list_threads(q.strip())]


@router.post("/threads", status_code=201)
def create_thread(body: ThreadCreate):
    case = clean_case(body.case_context)
    if case and body.preview_image:
        try:
            case["preview"] = prepare_image(body.preview_image, max_side=720)
        except ChatInputError as exc:
            raise HTTPException(400, str(exc)) from exc
    thread = store.create_thread(body.title.strip() or service.DEFAULT_TITLE, body.language, case)
    if case and body.assets:
        store.save_assets(thread["id"], tools.clean_assets([a.model_dump() for a in body.assets]))
    return thread


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str):
    thread = store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(404, "Conversation not found")
    return {**thread, "running": runs.active(thread_id) is not None}


@router.get("/threads/{thread_id}/stream")
def follow_thread(thread_id: str):
    """Re-attach to an answer that is still being written (replays it from the start)."""
    _thread_or_404(thread_id)
    run = runs.active(thread_id)
    if run is None:
        raise HTTPException(404, "No answer is being written in this conversation.")
    return _sse(run.follow())


@router.post("/threads/{thread_id}/stop")
async def stop_thread(thread_id: str):
    _thread_or_404(thread_id)
    return {"stopped": await runs.stop(thread_id)}


@router.patch("/threads/{thread_id}")
def update_thread(thread_id: str, body: ThreadUpdate):
    _thread_or_404(thread_id)
    return store.update_thread(thread_id, title=body.title, language=body.language)


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(thread_id: str):
    await runs.stop(thread_id)
    if not store.delete_thread(thread_id):
        raise HTTPException(404, "Conversation not found")


@router.post("/threads/{thread_id}/messages", dependencies=[Depends(rate_limited("chat"))])
async def send_message(thread_id: str, body: MessageCreate):
    thread = _thread_or_404(thread_id)
    content = body.content.strip()
    try:
        image = prepare_image(body.image)
    except ChatInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    attachment = None
    if body.attachment:
        found = tools.attachment_path(body.attachment.id)
        if found is None:
            raise HTTPException(410, "The attached scan expired. Attach it again.")
        attachment = {"id": body.attachment.id, "name": body.attachment.name, "kind": found[1]}
    if not content and not image and not attachment:
        raise HTTPException(400, "Write a message or attach an image.")
    default = (
        "Please analyse the attached scan." if attachment else "Please explain the attached image."
    )
    return _start(thread_id, service.send(thread, content or default, image, attachment))


@router.post(
    "/threads/{thread_id}/attachments",
    status_code=201,
    dependencies=[Depends(rate_limited("scan"))],
)
async def attach_scan(thread_id: str, files: list[UploadFile] = File(...)):
    """Upload a DICOM file or series for the assistant to analyse with the next message."""
    _thread_or_404(thread_id)
    if not files or len(files) > 1000:
        raise HTTPException(400, "Attach one .dcm file, a .zip of a series, or its slices.")
    first = (files[0].filename or "scan").rsplit("/", 1)[-1]
    single = len(files) == 1 and not first.lower().endswith(".zip")
    kind = "single" if single else "multi"
    path = await _save_upload(files, kind)
    name = first if len(files) == 1 else f"{len(files)} slices"
    return {"id": tools.store_attachment(path, kind), "name": name[:120], "kind": kind}


@router.post(
    "/threads/{thread_id}/messages/{message_id}/edit",
    dependencies=[Depends(rate_limited("chat"))],
)
async def edit_message(thread_id: str, message_id: str, body: MessageEdit):
    _thread_or_404(thread_id)
    if store.get_message(thread_id, message_id) is None:
        raise HTTPException(404, "Message not found")
    if runs.active(thread_id):
        raise HTTPException(409, "An answer is still being written in this conversation.")
    return _start(
        thread_id, service.edit(store.get_thread(thread_id), message_id, body.content.strip())
    )


@router.post("/threads/{thread_id}/regenerate", dependencies=[Depends(rate_limited("chat"))])
async def regenerate(thread_id: str):
    _thread_or_404(thread_id)
    return _start(thread_id, service.regenerate(store.get_thread(thread_id)))
