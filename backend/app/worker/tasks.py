"""Celery tasks. Models are loaded once per worker process, not per request."""

from __future__ import annotations

import logging
import os

from celery.signals import worker_process_init

from app.jobs.runner import JobError, analyze_upload
from app.worker.celery_app import ANALYZE_TASK, celery_app

log = logging.getLogger(__name__)


@worker_process_init.connect
def _warm_models(**_kwargs) -> None:
    if os.getenv("WORKER_PRELOAD_MODELS", "1") == "1":
        from app.ml.registry import get_registry

        get_registry().preload()


@celery_app.task(name=ANALYZE_TASK, bind=True)
def analyze(self, kind: str, upload_path: str) -> dict:
    def progress(value: int, message: str) -> None:
        self.update_state(state="PROGRESS", meta={"progress": int(value), "message": message})

    try:
        return {"ok": True, "result": analyze_upload(kind, upload_path, progress)}
    except JobError as exc:
        # Returned (not raised) so the user-facing message survives JSON result storage.
        return {"ok": False, "error": str(exc)}
