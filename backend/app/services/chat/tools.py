"""Assistant tools run by the app around an answer.

* show_images  - when the user asks to see a level, box or image, the matching annotated
                 slice, model crop and focus map are attached to the reply.
* analyze_scan - a DICOM file or series ZIP attached in the chat is graded by the
                 SpineScope models through the normal job queue; the result becomes the
                 conversation's scan context and its images are shown in the reply.

Tools are triggered by the app, not chosen by the language model, so they behave the same
with every provider in the fallback chain (including models without tool calling).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from app.core.config import get_settings
from app.services.chat import store
from app.services.chat.context import ChatInputError, clean_case, prepare_image

SEVERITY_RANK = {"Normal/Mild": 0, "Moderate": 1, "Severe": 2}
LEVEL = re.compile(r"\b(?:([lr])\s+)?l\s*([1-5])\s*[/\-–_ ]?\s*(l\s*[1-5]|s\s*1)\b", re.I)
LEFT = re.compile(r"\b(left|baen|baayen|bayen|bain|bayan)\b", re.I)
RIGHT = re.compile(r"\b(right|dayen|daen|daayen|dain|dayan)\b", re.I)
VISUAL = re.compile(
    r"\b(box(es)?|image|images|picture|pic|photo|show|display|view|see|slice|focus|heat\s?map"
    r"|crop|highlight|overlay|where|marked|dikh\w*|dekh\w*|tasve?e?r|tasvir|screenshot)\b",
    re.I,
)
MAX_ASSETS = 60


# ---------------------------------------------------------------------------- assets


def assets_from_result(result: dict) -> list[dict]:
    """Annotated slices, model crops and focus maps of an analysis, as bounded JPEGs."""
    assets = []
    for image in result.get("images", []):
        label = f"Slice {image['slice_number']}" if image.get("slice_number") else "Image"
        assets.append(
            {
                "key": f"slice:{image['index']}",
                "caption": f"{label} with level boxes",
                "image": image["annotated"],
            }
        )
    for f in result.get("findings", []):
        explanation = f.get("explanation") or {}
        name = f"{f['id']} {f['level_label']}, {f['severity']}"
        if explanation.get("heatmap_image"):
            assets.append(
                {
                    "key": f"focus:{f['id']}",
                    "caption": f"Focus map {name}",
                    "image": explanation["heatmap_image"],
                }
            )
        if explanation.get("crop_image"):
            assets.append(
                {
                    "key": f"crop:{f['id']}",
                    "caption": f"Model input {name}",
                    "image": explanation["crop_image"],
                }
            )
    return clean_assets(assets)


def clean_assets(assets: list | None) -> list[dict]:
    cleaned, budget = [], 15_000_000
    for item in (assets or [])[:MAX_ASSETS]:
        if not isinstance(item, dict) or not re.fullmatch(
            r"(slice|focus|crop):[\w-]{1,12}", str(item.get("key", ""))
        ):
            continue
        try:
            image = prepare_image(str(item.get("image") or ""), max_side=900)
        except ChatInputError:
            continue
        if not image or len(image) > budget:
            continue
        budget -= len(image)
        cleaned.append(
            {"key": item["key"], "caption": str(item.get("caption", ""))[:120], "image": image}
        )
    return cleaned


# ------------------------------------------------------------------------- show_images


def wants_images(text: str) -> bool:
    return bool(VISUAL.search(text or ""))


def mentioned(text: str) -> tuple[set[str], str | None]:
    levels, side = set(), None
    for prefix, upper, lower in LEVEL.findall(text or ""):
        lower = re.sub(r"\s", "", lower).upper()
        levels.add(f"L{upper}/{lower}")
        if prefix:
            side = "left" if prefix.lower() == "l" else "right"
    if LEFT.search(text or ""):
        side = "left"
    elif RIGHT.search(text or ""):
        side = "right"
    return levels, side


def pick_findings(case: dict, text: str, limit: int = 3) -> list[dict]:
    findings = (case or {}).get("findings") or []
    levels, side = mentioned(text)
    if levels:
        chosen = [
            f
            for f in findings
            if f.get("level", "").split(" ")[-1] in levels
            and (side is None or f.get("side") in (None, side))
        ]
    else:
        chosen = sorted(
            findings,
            key=lambda f: (SEVERITY_RANK.get(f.get("severity"), 0), bool(f.get("review_flags"))),
            reverse=True,
        )[:1]
    return chosen[:limit]


def images_for(thread_id: str, case: dict | None, text: str, force: bool = False) -> list[dict]:
    """Assets to show with the reply, or [] when the user did not ask to see anything."""
    if not case or not (force or wants_images(text)):
        return []
    available = store.asset_keys(thread_id)
    if not available:
        return []
    keys: list[str] = []
    for finding in pick_findings(case, text):
        for key in (
            f"slice:{finding.get('image_index', 0)}",
            f"focus:{finding['id']}",
            f"crop:{finding['id']}",
        ):
            if key in available and key not in keys:
                keys.append(key)
    if not keys:
        keys = sorted(k for k in available if k.startswith("slice:"))[:2]
    return store.get_assets(thread_id, keys[:6])


# ------------------------------------------------------------------------ analyze_scan


def attachment_path(attachment_id: str) -> tuple[Path, str] | None:
    if not re.fullmatch(r"[0-9a-f]{32}", attachment_id or ""):
        return None
    for suffix, kind in (("dcm", "single"), ("zip", "multi")):
        path = get_settings().upload_dir / f"chat-{attachment_id}.{suffix}"
        if path.is_file():
            return path, kind
    return None


def store_attachment(path: Path, kind: str) -> str:
    """Keep an uploaded scan until the next message analyses it; stale ones are removed."""
    folder = get_settings().upload_dir
    cutoff = time.time() - 3600
    for old in folder.glob("chat-*"):
        with contextlib.suppress(OSError):
            if old.stat().st_mtime < cutoff:
                old.unlink()
    attachment_id = uuid.uuid4().hex
    path.rename(folder / f"chat-{attachment_id}.{'dcm' if kind == 'single' else 'zip'}")
    return attachment_id


def scan_preview(path: Path, kind: str, side: int = 512) -> str | None:
    """A small JPEG of the attached scan (the middle slice of a series) for the progress card."""
    import base64
    import io
    import zipfile

    import pydicom
    from PIL import Image

    from app.ml.dicom import pixels, read_dataset, to_uint8

    try:
        if kind == "single":
            raw = path.read_bytes()
        else:
            with zipfile.ZipFile(path) as archive:
                names = [n for n in archive.namelist() if not n.endswith("/")][:1000]
                order = []
                for name in names:
                    with archive.open(name) as handle:
                        head = handle.read(64 * 1024)
                    try:
                        header = pydicom.dcmread(
                            io.BytesIO(head), stop_before_pixels=True, force=True
                        )
                        number = int(getattr(header, "InstanceNumber", 0))
                    except Exception:  # noqa: BLE001 - not a DICOM header; sort it last
                        number = 10**6
                    order.append((number, name))
                order.sort()
                raw = archive.read(order[len(order) // 2][1])
        dataset = read_dataset(raw)
        image = Image.fromarray(
            to_uint8(pixels(dataset), str(getattr(dataset, "PhotometricInterpretation", "")))
        ).convert("RGB")
        image.thumbnail((side, side))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=80)
        return base64.b64encode(output.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 - the preview is decoration; the analysis reports errors
        return None


def summarize(result: dict) -> str:
    counts = (result.get("summary") or {}).get("counts", {})
    parts = [
        f"{counts.get(name, 0)} {label}"
        for name, label in (
            ("Severe", "severe"),
            ("Moderate", "moderate"),
            ("Normal/Mild", "normal/mild"),
        )
    ]
    return f"{result.get('condition_name', 'Scan')}: " + ", ".join(parts)


async def analyze_scan(thread: dict, attachment: dict) -> AsyncIterator[dict]:
    """Run the SpineScope pipeline on an attached file; yields tool events, then 'result'."""
    from app.jobs.queue import get_queue

    tool = {
        "id": uuid.uuid4().hex[:8],
        "name": "analyze_scan",
        "label": f"Analysing {attachment.get('name') or 'scan'} with SpineScope",
        "status": "running",
        "progress": 0,
        "message": "Queued",
    }
    found = attachment_path(attachment.get("id", ""))
    if not found:
        yield {
            "type": "tool",
            "tool": {
                **tool,
                "status": "error",
                "message": "The attached file is no longer available.",
            },
        }
        return
    path, kind = found
    yield {"type": "tool", "tool": {**tool, "message": "Preparing the scan"}}
    # The preview is read before the job starts: the worker deletes the upload when it is done.
    preview = await asyncio.to_thread(scan_preview, path, kind)
    if preview:
        tool["preview"] = preview
    started = time.time()
    queue = get_queue()
    try:
        job_id = await asyncio.to_thread(queue.submit, kind, path)
    except Exception:  # noqa: BLE001
        path.unlink(missing_ok=True)
        yield {
            "type": "tool",
            "tool": {**tool, "status": "error", "message": "The analysis queue is not available."},
        }
        return
    yield {"type": "tool", "tool": tool}
    last = None
    while time.time() - started < get_settings().task_time_limit_seconds:
        status = await asyncio.to_thread(queue.status, job_id) or {}
        state = status.get("state")
        if state == "succeeded":
            result = status["result"]
            timings = result.get("timings") or {}
            done = {
                **tool,
                "status": "done",
                "progress": 100,
                "message": summarize(result),
                "seconds": round(time.time() - started, 1),
                "model_seconds": timings.get("model_seconds"),
                "queue_seconds": timings.get("queue_seconds"),
            }
            yield {"type": "tool", "tool": done}
            yield {"type": "result", "result": result, "tool": done}
            return
        if state == "failed":
            yield {
                "type": "tool",
                "tool": {
                    **tool,
                    "status": "error",
                    "message": status.get("error") or "Analysis failed.",
                },
            }
            return
        current = (status.get("progress"), status.get("message"))
        if current != last:
            last = current
            yield {
                "type": "tool",
                "tool": {
                    **tool,
                    "progress": status.get("progress", 0),
                    "message": status.get("message") or "Working",
                },
            }
        await asyncio.sleep(0.6)
    yield {
        "type": "tool",
        "tool": {
            **tool,
            "status": "error",
            "message": "The analysis took too long and was stopped.",
        },
    }


def adopt_result(thread: dict, result: dict) -> dict:
    """Store an analysis as the conversation's scan context and image assets."""
    case = clean_case(result) or {}
    slices = [img for img in result.get("images", []) if img.get("annotated")]
    if slices:
        with contextlib.suppress(ChatInputError):
            case["preview"] = prepare_image(slices[0]["annotated"], max_side=720)
    store.set_case(thread["id"], case)
    store.save_assets(thread["id"], assets_from_result(result))
    thread["case_context"] = case
    return case
