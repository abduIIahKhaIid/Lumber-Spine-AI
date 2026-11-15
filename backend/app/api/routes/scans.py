"""Scan upload -> background job -> polled status/result, plus the PDF report."""

from __future__ import annotations

import base64
import uuid
import zipfile
from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.core.config import get_settings
from app.core.security import rate_limited
from app.jobs.queue import get_queue

router = APIRouter(prefix="/api", tags=["scans"])


async def _copy(upload: UploadFile, output, limit: int, size: int) -> int:
    while chunk := await upload.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, f"Upload exceeds {get_settings().max_upload_mb} MB.")
        output.write(chunk)
    return size


def _suffix(upload: UploadFile) -> str:
    name = (upload.filename or "").lower()
    return "." + name.rsplit(".", 1)[1] if "." in name.rsplit("/", 1)[-1] else ""


async def _save_upload(files: list[UploadFile], kind: str):
    """One .dcm (single), or one .zip / several .dcm files of one series (multi)."""
    settings = get_settings()
    suffixes = [_suffix(f) for f in files]
    images = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
    if any(s in images for s in suffixes):
        raise HTTPException(
            415,
            "PNG/JPG images cannot be graded: the models need DICOM (.dcm) files, which carry the "
            "plane and sequence. Ask about a picture in the Assistant instead.",
        )
    if kind == "single" and (len(files) != 1 or suffixes[0] not in (".dcm", ".dicom", "")):
        raise HTTPException(415, "Upload one .dcm DICOM file.")
    zipped = kind == "multi" and len(files) == 1 and suffixes[0] == ".zip"
    if kind == "multi" and not zipped and any(s not in (".dcm", ".dicom", "") for s in suffixes):
        raise HTTPException(415, "Upload a .zip of one series, or the series' .dcm files.")
    if kind == "multi" and not zipped and len(files) < 3:
        raise HTTPException(400, "A series needs at least 3 slices. Use Single slice for one file.")

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"{uuid.uuid4().hex}.{'zip' if kind == 'multi' else 'dcm'}"
    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    try:
        if kind == "multi" and not zipped:
            # Loose slices are packed into one archive so the worker sees a normal series ZIP.
            with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
                for index, upload in enumerate(files):
                    with archive.open(f"slice-{index:04d}.dcm", "w") as output:
                        size = await _copy(upload, output, limit, size)
        else:
            with path.open("wb") as output:
                size = await _copy(files[0], output, limit, size)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(400, "The uploaded file is empty.")
    return path


@router.post("/scans/{kind}", status_code=202, dependencies=[Depends(rate_limited("scan"))])
async def submit_scan(
    kind: str,
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
):
    if kind not in ("single", "multi"):
        raise HTTPException(404, "Unknown scan workflow")
    uploads = [f for f in ([file] if file else []) + (files or []) if f is not None]
    if not uploads:
        raise HTTPException(400, "Choose a file to upload.")
    if len(uploads) > 1000:
        raise HTTPException(413, "Too many files. Upload one series at a time.")
    path = await _save_upload(uploads, kind)
    queue = get_queue()
    try:
        job_id = queue.submit(kind, path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(503, "The analysis queue is not available.") from exc
    return {"job_id": job_id, "queue": queue.name, "status_url": f"/api/jobs/{job_id}"}


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    status = get_queue().status(job_id)
    if status is None:
        raise HTTPException(404, "Job not found or expired")
    return status


@router.get("/jobs/{job_id}/report.pdf")
def job_report(job_id: str, label: str = Query(default="", max_length=80)):
    status = get_queue().status(job_id)
    if not status or status["state"] != "succeeded":
        raise HTTPException(404, "No finished analysis for this job")
    from app.services.reports.scan_report import build_scan_report

    pdf = build_scan_report(status["result"], label)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="spine-analysis-{job_id[:8]}.pdf"'},
    )


@router.post("/convert-dicom", dependencies=[Depends(rate_limited("convert"))])
async def convert_dicom(file: UploadFile = File(...)):
    """DICOM -> JPEG preview, used when a DICOM is attached in the assistant."""
    from PIL import Image

    from app.ml.dicom import UnsupportedScan, deidentify, pixels, read_dataset, to_uint8

    raw = await file.read(30 * 1024 * 1024 + 1)
    if len(raw) > 30 * 1024 * 1024:
        raise HTTPException(413, "DICOM must be smaller than 30 MB.")
    try:
        dataset = deidentify(read_dataset(raw))
        image = to_uint8(pixels(dataset), str(getattr(dataset, "PhotometricInterpretation", "")))
    except UnsupportedScan as exc:
        raise HTTPException(400, str(exc)) from exc
    output = BytesIO()
    Image.fromarray(image).convert("RGB").save(output, format="JPEG", quality=90)
    return {"jpegBase64": base64.b64encode(output.getvalue()).decode("ascii")}
