"""Job queue facade: Celery + Redis when available, an in-process queue otherwise.

Both backends expose the same status document so the API and the frontend do not care
which one ran the job:

    {"id", "state": queued|running|succeeded|failed, "progress", "message", "result"?, "error"?}
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

log = logging.getLogger(__name__)


class JobQueue(Protocol):
    name: str

    def submit(self, kind: str, upload_path: Path) -> str: ...

    def status(self, job_id: str) -> dict | None: ...

    def health(self) -> dict: ...


def with_live_timing(doc: dict, timing: dict | None) -> dict:
    """Adds the finished steps' times and how long the current step has been running."""
    if timing and doc.get("state") == "running":
        doc["timing"] = {
            "stages": timing.get("stages", []),
            "stage": timing.get("stage"),
            "stage_elapsed": round(max(0.0, time.time() - timing.get("stage_started_at", 0)), 3),
        }
    return doc


def _doc(job_id, state, progress=0, message="", result=None, error=None) -> dict:
    doc = {"id": job_id, "state": state, "progress": progress, "message": message}
    if result is not None:
        doc["result"] = result
    if error is not None:
        doc["error"] = error
    return doc


class LocalQueue:
    """Single worker thread inside the API process. For development without Redis."""

    name = "local"

    def __init__(self, ttl_seconds: int = 3600):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
        self._ttl = ttl_seconds

    def _update(self, job_id: str, **changes) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(changes)

    def _run(self, job_id: str, kind: str, upload_path: Path, submitted_at: float) -> None:
        from app.jobs.runner import JobError, analyze_upload

        self._update(job_id, state="running", message="Starting analysis")
        try:
            result = analyze_upload(
                kind,
                str(upload_path),
                lambda value, message, timing=None: self._update(
                    job_id, progress=int(value), message=message, timing=timing
                ),
                submitted_at,
            )
        except JobError as exc:
            self._update(job_id, state="failed", error=str(exc), message="Analysis failed")
        except Exception:  # noqa: BLE001 - never leave a job stuck in "running"
            log.exception("local job crashed")
            self._update(job_id, state="failed", error="Analysis failed unexpectedly.")
        else:
            self._update(job_id, state="succeeded", progress=100, message="Complete", result=result)

    def _expire(self) -> None:
        cutoff = time.time() - self._ttl
        with self._lock:
            for job_id in [k for k, v in self._jobs.items() if v["created"] < cutoff]:
                del self._jobs[job_id]

    def submit(self, kind: str, upload_path: Path) -> str:
        self._expire()
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {
                **_doc(job_id, "queued", message="Waiting for the analysis worker"),
                "created": time.time(),
            }
        self._executor.submit(self._run, job_id, kind, upload_path, time.time())
        return job_id

    def status(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            doc = {k: v for k, v in job.items() if k not in ("created", "timing")}
        return with_live_timing(doc, job.get("timing"))

    def health(self) -> dict:
        return {"backend": self.name, "ready": True}


class CeleryQueue:
    name = "celery"

    def __init__(self):
        from app.worker.celery_app import celery_app

        self.app = celery_app

    def submit(self, kind: str, upload_path: Path) -> str:
        from app.worker.celery_app import ANALYZE_TASK

        return self.app.send_task(ANALYZE_TASK, args=[kind, str(upload_path), time.time()]).id

    def status(self, job_id: str) -> dict | None:
        from celery.result import AsyncResult

        result = AsyncResult(job_id, app=self.app)
        state = result.state
        if state == "PENDING":
            return _doc(job_id, "queued", message="Waiting for an analysis worker")
        if state in ("STARTED", "RECEIVED", "RETRY"):
            return _doc(job_id, "running", 2, "Worker started")
        if state == "PROGRESS":
            meta = result.info if isinstance(result.info, dict) else {}
            doc = _doc(job_id, "running", meta.get("progress", 0), meta.get("message", ""))
            return with_live_timing(doc, meta.get("timing"))
        if state == "SUCCESS":
            payload = result.result or {}
            if payload.get("ok"):
                return _doc(job_id, "succeeded", 100, "Complete", result=payload["result"])
            return _doc(job_id, "failed", 100, "Analysis failed", error=payload.get("error"))
        return _doc(job_id, "failed", 100, "Analysis failed", error="The analysis worker failed.")

    def health(self) -> dict:
        try:
            with self.app.connection_for_write() as connection:
                connection.ensure_connection(max_retries=1, timeout=2)
            workers = self.app.control.inspect(timeout=1.0).ping() or {}
        except Exception as exc:  # noqa: BLE001
            return {"backend": self.name, "ready": False, "reason": f"broker unreachable: {exc}"}
        return {"backend": self.name, "ready": bool(workers), "workers": sorted(workers)}


def _redis_reachable(url: str) -> bool:
    try:
        import redis

        client = redis.Redis.from_url(url, socket_connect_timeout=1.5, socket_timeout=1.5)
        return bool(client.ping())
    except Exception:  # noqa: BLE001
        return False


_queue: JobQueue | None = None
_queue_lock = threading.Lock()


def get_queue() -> JobQueue:
    global _queue
    with _queue_lock:
        if _queue is None:
            settings = get_settings()
            choice = settings.job_backend
            if choice == "celery" or (
                choice == "auto" and settings.redis_url and _redis_reachable(settings.redis_url)
            ):
                _queue = CeleryQueue()
            else:
                if choice == "auto" and settings.redis_url:
                    log.warning("Redis is not reachable; using the in-process job queue")
                _queue = LocalQueue(settings.job_ttl_seconds)
            log.info("job queue: %s", _queue.name)
        return _queue


def reset_queue() -> None:
    global _queue
    with _queue_lock:
        _queue = None
