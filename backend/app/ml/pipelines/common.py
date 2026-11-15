"""Shared result assembly for the single-image and series pipelines."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from app.ml.dicom import CONDITION_NAMES
from app.ml.explain import explain, png_base64
from app.ml.provenance import calibrated_scores
from app.ml.quality import review_signal
from app.ml.registry import LEVELS, SeverityModel
from app.ml.render import annotate
from app.ml.severity import ORDER, RANK, ordered_scores
from app.services.recommendations.engine import recommend

Progress = Callable[[int, str], None]


def noop_progress(_value: int, _message: str) -> None:
    return None


def level_parts(label: str) -> tuple[str, str | None]:
    """'L_L4/L5' or 'left_L4/L5' -> ('L4/L5', 'left'); 'L4/L5' -> ('L4/L5', None)."""
    for prefix, side in (("left_", "left"), ("right_", "right"), ("L_", "left"), ("R_", "right")):
        if label.startswith(prefix):
            return label[len(prefix) :], side
    return label, None


def display_label(level: str, side: str | None) -> str:
    return f"{side[0].upper()} {level}" if side else level


def classify_crop(severity: SeverityModel, tensor: torch.Tensor, crop: Image.Image) -> dict:
    """Run SeverityNet on one crop and return ordered scores plus a focus map."""
    with torch.inference_mode():
        logits = severity.model(tensor)
        probs = F.softmax(logits, dim=1)[0].tolist()
    index = int(np.argmax(probs))
    label = severity.classes[index]
    return {
        "severity": label,
        "severity_confidence": round(float(probs[index]), 4),
        "class_scores": ordered_scores(dict(zip(severity.classes, probs))),
        "logits": logits,
        "explanation": explain(severity.model, tensor, index, crop, label),
    }


def finding(
    *,
    index: int,
    condition: str,
    label: str,
    box: list[int],
    point: list[float],
    image_index: int,
    slice_number: int | None,
    scored: dict,
    severity: SeverityModel,
    localization: float | None,
    extra_reasons: list[str] | None = None,
) -> dict:
    level, side = level_parts(label)
    uncertainty = review_signal(scored["class_scores"], localization)
    if extra_reasons:
        uncertainty["status"] = "review"
        uncertainty["reasons"].extend(extra_reasons)
    return {
        "id": f"F{index}",
        "key": f"{condition}:{side[0].upper() + '_' if side else ''}{level}",
        "condition": condition,
        "condition_name": CONDITION_NAMES[condition],
        "level": level,
        "side": side,
        "level_label": display_label(level, side),
        "severity": scored["severity"],
        "severity_confidence": scored["severity_confidence"],
        "class_scores": scored["class_scores"],
        "localization_confidence": None if localization is None else round(float(localization), 4),
        "box": [int(v) for v in box],
        "point": [round(float(v), 1) for v in point],
        "image_index": image_index,
        "slice_number": slice_number,
        "uncertainty": uncertainty,
        "calibration": calibrated_scores(scored["logits"], severity.classes, condition),
        "explanation": scored["explanation"],
    }


def sort_findings(findings: list[dict]) -> list[dict]:
    side_rank = {None: 0, "left": 0, "right": 1}
    findings.sort(key=lambda f: (side_rank[f["side"]], LEVELS.index(f["level"])))
    for number, item in enumerate(findings, start=1):
        item["id"] = f"F{number}"
    return findings


def summary(condition: str, findings: list[dict], mode: str = "multi") -> dict:
    counts = {name: sum(f["severity"] == name for f in findings) for name in ORDER}
    worst = max(findings, key=lambda f: RANK.get(f["severity"], 0), default=None)
    sides = ("left", "right") if condition != "SCS" else (None,)
    if mode == "single" and condition != "SCS":
        # One sagittal/axial slice shows the side(s) it cuts through; judge coverage there.
        sides = tuple(sorted({f["side"] for f in findings})) or sides
    expected = {(level, side) for level in LEVELS for side in sides}
    assessed = {(f["level"], f["side"]) for f in findings}
    missing = sorted(expected - assessed, key=lambda item: (str(item[1]), item[0]))
    return {
        "counts": counts,
        "total": len(findings),
        "max_severity": worst["severity"] if worst else None,
        "flagged": sum(f["uncertainty"]["status"] == "review" for f in findings),
        "not_assessed": [display_label(level, side) for level, side in missing],
    }


def image_entry(index: int, image_u8: np.ndarray, findings: list[dict], slice_number: int | None):
    on_image = [f for f in findings if f["image_index"] == index]
    title = f"Slice {slice_number}" if slice_number else None
    return {
        "index": index,
        "slice_number": slice_number,
        "width": int(image_u8.shape[1]),
        "height": int(image_u8.shape[0]),
        "original": png_base64(Image.fromarray(image_u8).convert("RGB")),
        "annotated": png_base64(annotate(image_u8, on_image, title)),
    }


def assemble(
    *,
    mode: str,
    info: dict,
    findings: list[dict],
    images: list[dict],
    quality: dict,
    provenance: dict,
) -> dict:
    for item in findings:
        item.pop("logits", None)
    condition = info["condition"]
    result = {
        "analysis_id": provenance["analysis_id"],
        "mode": mode,
        "condition": condition,
        "condition_name": CONDITION_NAMES[condition],
        "plane": info["plane"],
        "sequence": info["sequence"],
        "images": images,
        "findings": findings,
        "summary": summary(condition, findings, mode),
        "quality": quality,
        "provenance": provenance,
        "privacy": {
            "processing": "in_memory",
            "note": "Identifiers are removed in memory; uploads are deleted after analysis.",
        },
        "created_at": datetime.now(UTC).isoformat(),
    }
    result["recommendations"] = recommend(result)
    return result
