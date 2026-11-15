"""Checkpoint fingerprints and opt-in temperature calibration. No patient metadata."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings
from app.ml.severity import ordered_scores

PIPELINE_VERSION = "3.0.0"


@lru_cache(maxsize=32)
def _fingerprint(path: str, size: int, modified: int) -> str:
    digest = sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> str | None:
    if not path.is_file():
        return None
    info = path.stat()
    return _fingerprint(str(path), info.st_size, info.st_mtime_ns)


def calibration_for(condition: str) -> tuple[float | None, str]:
    settings = get_settings()
    path = settings.calibration_file
    if not path.is_file():
        return None, "No fitted calibration artifact"
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        record = artifact["conditions"][condition]
        if not artifact.get("deployment_approved_by"):
            return None, "Evaluation artifact has not been approved for inference"
        current = fingerprint(settings.model_dir / f"severity_model_full_{condition.lower()}.pth")
        if record.get("checkpoint_sha256") != current:
            return None, "Calibration checkpoint fingerprint does not match"
        temperature = float(record["temperature"])
        if not math.isfinite(temperature) or not 0.01 <= temperature <= 100:
            return None, "Invalid calibration temperature"
        return temperature, artifact.get("dataset", "Unspecified evaluation dataset")
    except (KeyError, ValueError, TypeError, OSError):
        return None, "Calibration artifact is unavailable or invalid"


def calibrated_scores(logits, classes, condition: str) -> dict:
    temperature, evidence = calibration_for(condition)
    if temperature is None:
        return {"status": "unavailable", "reason": evidence, "scores": {}}
    scores = (logits.detach() / temperature).softmax(dim=1)[0].tolist()
    return {
        "status": "applied",
        "method": "Temperature scaling",
        "temperature": temperature,
        "dataset": evidence,
        "scores": ordered_scores(dict(zip(classes, scores))),
    }


def provenance(condition: str, workflow: str, acquisition: dict) -> dict:
    settings = get_settings()
    suffix = condition.lower()
    names = [f"severity_model_full_{suffix}.pth"] + (
        [f"best_{suffix}.pt"]
        if workflow == "single"
        else [f"stage1_{suffix}.pt", f"stage2_{suffix}.pt"]
    )
    checkpoints = {
        name: digest
        for name in names
        if (digest := fingerprint(settings.model_dir / name)) is not None
    }
    temperature, note = calibration_for(condition)
    return {
        "analysis_id": str(uuid4()),
        "pipeline_version": PIPELINE_VERSION,
        "workflow": workflow,
        "condition": condition,
        "checkpoints_sha256": checkpoints,
        "calibration": "applied" if temperature is not None else "unavailable",
        "calibration_note": note,
        "acquisition": acquisition,
        "acquisition_signature": sha256(
            json.dumps(acquisition, sort_keys=True).encode()
        ).hexdigest(),
    }
