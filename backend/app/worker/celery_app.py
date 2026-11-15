"""Celery application shared by the API (producer) and the worker (consumer).

Importing this module stays light: it never imports torch or the model code.

Run a worker:  celery -A app.worker.celery_app worker --loglevel=info
On Windows:    celery -A app.worker.celery_app worker --loglevel=info --pool=solo
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()
broker = settings.redis_url or "redis://localhost:6379/0"

celery_app = Celery("lumber_spine", broker=broker, backend=broker)
celery_app.conf.update(
    task_default_queue="analysis",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,  # PENDING -> STARTED -> PROGRESS -> SUCCESS/FAILURE
    task_acks_late=True,  # a crashed worker does not lose the job ...
    task_reject_on_worker_lost=True,  # ... it goes back to the queue
    worker_prefetch_multiplier=1,  # long CPU tasks: one at a time per process
    result_expires=settings.job_ttl_seconds,
    task_time_limit=settings.task_time_limit_seconds,
    task_soft_time_limit=max(30, settings.task_time_limit_seconds - 30),
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=3,
    imports=("app.worker.tasks",),
)

ANALYZE_TASK = "scans.analyze"
