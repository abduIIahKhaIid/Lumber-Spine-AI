"""Scan upload -> background job -> polled status/result, plus the PDF report."""

from __future__ import annotations

import base64
import uuid
from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.core.config import get_settings
from app.core.security import rate_limited
from app.jobs.queue import get_queue

router = APIRouter(prefix="/api", tags=["scans"])
EXTENSIONS = {"single": (".dcm", ".dicom", ""), "multi": (".zip",)}


async def _save_upload(file: UploadFile, kind: str):
    settings = get_settings()
    name = (file.filename or "").lower()
    suffix = "." + name.rsplit(".", 1)[1] if "." in name else ""
    if suffix not in EXTENSIONS[kind]:
        expected = "a .dcm DICOM file" if kind == "single" else "a .zip archive of one series"
        raise HTTPException(415, f"Upload {expected}.")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"{uuid.uuid4().hex}.{'zip' if kind == 'multi' else 'dcm'}"
    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    with path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                output.close()
                path.unlink(missing_ok=True)
                raise HTTPException(413, f"Upload exceeds {settings.max_upload_mb} MB.")
            output.write(chunk)
    if size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(400, "The uploaded file is empty.")
    return path


@router.post("/scans/{kind}", status_code=202, dependencies=[Depends(rate_limited("scan"))])
async def submit_scan(kind: str, file: UploadFile = File(...)):
    if kind not in EXTENSIONS:
        raise HTTPException(404, "Unknown scan workflow")
    path = await _save_upload(file, kind)
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
