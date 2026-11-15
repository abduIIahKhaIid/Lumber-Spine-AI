"""Scan upload -> job queue -> polling, with the in-process queue and with Celery + Redis."""

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.jobs import runner
from app.main import create_app


def fake_analysis(kind, upload_path, progress):
    from pathlib import Path

    Path(upload_path).unlink(missing_ok=True)
    progress(50, "halfway")
    if kind == "multi":
        raise runner.JobError("The archive mixes series for different conditions.")
    return {"analysis_id": "x", "mode": kind, "findings": [], "summary": {}, "images": []}


def poll(client, job_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["state"] in ("succeeded", "failed"):
            return status
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_local_queue_success_failure_and_cleanup(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "analyze_upload", fake_analysis)
    with TestClient(create_app()) as client:
        accepted = client.post(
            "/api/scans/single", files={"file": ("scan.dcm", b"DICM-bytes", "application/dicom")}
        )
        assert accepted.status_code == 202 and accepted.json()["queue"] == "local"
        done = poll(client, accepted.json()["job_id"])
        assert done["state"] == "succeeded" and done["result"]["mode"] == "single"

        failed = poll(
            client,
            client.post(
                "/api/scans/multi", files={"file": ("s.zip", b"PK..", "application/zip")}
            ).json()["job_id"],
        )
        assert failed["state"] == "failed" and "mixes series" in failed["error"]
    uploads = tmp_path / "data" / "uploads"
    assert not any(uploads.iterdir())  # uploads never outlive their job


def test_upload_validation():
    with TestClient(create_app()) as client:
        png = client.post("/api/scans/single", files={"file": ("a.png", b"x")})
        assert png.status_code == 415 and "DICOM" in png.json()["detail"]
        assert client.post("/api/scans/multi", files={"file": ("a.zip", b"")}).status_code == 400
        assert client.post("/api/scans/other", files={"file": ("a.zip", b"x")}).status_code == 404
        assert client.get("/api/jobs/missing").status_code == 404
        assert client.get("/health").json()["status"] == "ok"


def test_multi_accepts_loose_dicom_slices(monkeypatch):
    import zipfile as zf

    seen = {}

    def capture(kind, upload_path, progress):
        with zf.ZipFile(upload_path) as archive:
            seen["names"] = archive.namelist()
        return fake_analysis(kind, upload_path, lambda *_: None) if kind == "single" else {}

    monkeypatch.setattr(runner, "analyze_upload", capture)
    with TestClient(create_app()) as client:
        files = [("files", (f"IM{i}.dcm", b"DICM" + bytes([i]))) for i in range(4)]
        job = client.post("/api/scans/multi", files=files).json()["job_id"]
        assert poll(client, job)["state"] == "succeeded"
        too_few = client.post("/api/scans/multi", files=files[:2])
        assert too_few.status_code == 400
    assert seen["names"] == [f"slice-{i:04d}.dcm" for i in range(4)]


def test_report_pdf_for_finished_job(monkeypatch, sample_result):
    monkeypatch.setattr(runner, "analyze_upload", lambda kind, path, progress: sample_result)
    with TestClient(create_app()) as client:
        job = client.post("/api/scans/multi", files={"file": ("s.zip", b"PK")}).json()["job_id"]
        poll(client, job)
        pdf = client.get(f"/api/jobs/{job}/report.pdf", params={"label": "Case 7"})
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def _redis_available():
    url = os.getenv("REDIS_URL")
    if not url:
        return False
    try:
        import redis

        return redis.Redis.from_url(url, socket_connect_timeout=1).ping()
    except Exception:
        return False


@pytest.mark.skipif(not _redis_available(), reason="needs REDIS_URL with a running Redis")
def test_celery_worker_round_trip(monkeypatch):
    """Real Redis broker + an in-process Celery worker running the task."""
    from celery.contrib.testing.worker import start_worker

    monkeypatch.setenv("JOB_BACKEND", "celery")
    monkeypatch.setenv("WORKER_PRELOAD_MODELS", "0")
    monkeypatch.setattr(runner, "analyze_upload", fake_analysis)
    import app.worker.tasks as tasks

    monkeypatch.setattr(tasks, "analyze_upload", fake_analysis)
    from app.worker.celery_app import celery_app

    with (
        start_worker(celery_app, perform_ping_check=False, pool="solo", loglevel="WARNING"),
        TestClient(create_app()) as client,
    ):
        accepted = client.post("/api/scans/single", files={"file": ("a.dcm", b"DICM")})
        assert accepted.json()["queue"] == "celery"
        done = poll(client, accepted.json()["job_id"], timeout=60)
        assert done["state"] == "succeeded", done
        failed = poll(
            client,
            client.post("/api/scans/multi", files={"file": ("a.zip", b"PK")}).json()["job_id"],
            timeout=60,
        )
        assert failed["state"] == "failed" and "mixes series" in failed["error"]
