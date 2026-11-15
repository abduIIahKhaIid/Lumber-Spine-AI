"""Liveness and readiness probes (used by Docker, CI smoke tests and future hosting)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.jobs.queue import get_queue
from app.services.chat import providers

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    settings = get_settings()
    return {"status": "ok", "app": settings.app_name, "version": settings.version}


@router.get("/ready")
def ready():
    settings = get_settings()
    queue = get_queue().health()
    models = {
        name: (settings.model_dir / name).is_file()
        for name in (
            "severity_model_full_scs.pth",
            "severity_model_full_nfn.pth",
            "severity_model_full_ss.pth",
        )
    }
    body = {
        "status": "ready" if queue.get("ready") else "degraded",
        "queue": queue,
        "models_present": models,
        "assistant_providers": [c.label for c in providers.candidates()],
    }
    return JSONResponse(body, status_code=200 if queue.get("ready") else 503)
