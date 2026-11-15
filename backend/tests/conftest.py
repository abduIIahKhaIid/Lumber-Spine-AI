"""Test isolation: every test gets its own data directory, settings, queue and limiter."""

from __future__ import annotations

import pytest

from app.core import config
from app.core.security import limiter
from app.db import database
from app.jobs import queue
from app.services.chat.router import cooldowns


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JOB_BACKEND", "local")
    monkeypatch.setenv("REVIEW_ACCESS_TOKEN", "test-key")
    monkeypatch.setenv("REVIEWER_NAME", "Dr Test")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1000")
    for name in ("GROQ_API_KEY", "GEMINI_API_KEY", "OLLAMA_BASE_URL", "OLLAMA_API_KEY"):
        monkeypatch.setenv(name, "")
    config.get_settings.cache_clear()
    database._initialized.clear()
    queue.reset_queue()
    limiter.reset()
    cooldowns.clear()
    yield
    config.get_settings.cache_clear()
    queue.reset_queue()


def make_finding(fid: str, level: str, severity: str, side=None, condition="SCS", review=False):
    scores = {"Normal/Mild": 0.1, "Moderate": 0.1, "Severe": 0.1}
    scores[severity] = 0.8
    return {
        "id": fid,
        "key": f"{condition}:{level}",
        "condition": condition,
        "condition_name": "Spinal canal stenosis",
        "level": level,
        "side": side,
        "level_label": f"{side[0].upper()} {level}" if side else level,
        "severity": severity,
        "severity_confidence": 0.8,
        "class_scores": scores,
        "localization_confidence": None,
        "box": [10, 10, 40, 40],
        "point": [25, 25],
        "image_index": 0,
        "slice_number": 1,
        "uncertainty": {
            "status": "review" if review else "no_flag",
            "reasons": ["Top severity score is below 0.60."] if review else [],
            "method": "test",
        },
        "calibration": {"status": "unavailable", "scores": {}},
        "explanation": {"crop_image": None, "heatmap_image": None, "method": "test"},
    }


@pytest.fixture
def sample_result():
    from app.services.recommendations.engine import recommend

    findings = [
        make_finding("F1", "L3/L4", "Moderate"),
        make_finding("F2", "L4/L5", "Severe"),
        make_finding("F3", "L5/S1", "Normal/Mild", review=True),
    ]
    result = {
        "analysis_id": "a1",
        "mode": "multi",
        "condition": "SCS",
        "condition_name": "Spinal canal stenosis",
        "plane": "Sagittal",
        "sequence": "T2",
        "images": [],
        "findings": findings,
        "summary": {
            "counts": {"Normal/Mild": 1, "Moderate": 1, "Severe": 1},
            "total": 3,
            "max_severity": "Severe",
            "flagged": 1,
            "not_assessed": ["L1/L2", "L2/L3"],
        },
        "quality": {"status": "pass", "issues": [], "method": "test"},
        "provenance": {"pipeline_version": "3.0.0", "calibration": "unavailable"},
        "created_at": "2026-11-16T00:00:00+00:00",
    }
    result["recommendations"] = recommend(result)
    return result
