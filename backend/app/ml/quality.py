"""Transparent input checks and review signals. None of these is a clinical score."""

from __future__ import annotations

import cv2
import numpy as np

from app.ml.dicom import to_uint8


def assess_image(image: np.ndarray) -> dict:
    values = np.asarray(image)
    if values.ndim > 2:
        values = values[..., 0]
    height, width = values.shape[:2]
    data = np.asarray(values, dtype=np.float32)
    finite = data[np.isfinite(data)]
    issues: list[str] = []
    if min(height, width) < 128:
        issues.append("Image dimensions are small for reliable visual review.")
    if finite.size != data.size:
        issues.append("Image has non-finite pixel values.")
    if finite.size:
        p1, p99 = np.percentile(finite, (1, 99))
        if p99 - p1 < 1:
            issues.append("Image has very little intensity variation.")
        sharpness = float(cv2.Laplacian(to_uint8(values), cv2.CV_64F).var())
        if sharpness < 20:
            issues.append(
                "Low edge detail: possible blur. Inspect the original image "
                "(threshold not clinically validated)."
            )
    else:
        issues.append("Image has no usable pixel values.")
    return {
        "status": "review" if issues else "pass",
        "issues": issues,
        "dimensions": [int(width), int(height)],
        "method": "Basic dimension, intensity and edge checks; not a validated quality score.",
    }


def assess_series(images: list[np.ndarray], records: list[dict]) -> dict:
    quality = assess_image(images[len(images) // 2])
    issues = list(quality["issues"])
    if len(images) < 5:
        issues.append("Series has fewer than five readable slices.")
    if len({row["series_uid"] for row in records}) > 1:
        issues.append("Archive contains more than one DICOM series; verify slice ordering.")
    flagged = sum(assess_image(image)["status"] == "review" for image in images)
    if flagged:
        issues.append(f"{flagged} of {len(images)} slices have basic image-quality flags.")
    numbers = sorted(row["instance_number"] for row in records)
    if len(set(numbers)) != len(numbers):
        issues.append("Duplicate instance numbers; verify slice ordering.")
    if any(b - a > 1 for a, b in zip(numbers, numbers[1:])):
        issues.append("Gaps in instance numbering; verify the series is complete.")
    positions = [row.get("position", []) for row in records]
    orientation = records[0].get("orientation", []) if records else []
    if len(orientation) == 6 and len(positions) > 2 and all(len(p) == 3 for p in positions):
        normal = np.cross(orientation[:3], orientation[3:])
        gaps = np.diff(np.sort(np.asarray(positions) @ normal))
        positive = gaps[gaps > 1e-4]
        if len(positive) < len(gaps):
            issues.append("Repeated slice positions; inspect duplicates before interpretation.")
        if positive.size and positive.max() > 1.5 * np.median(positive):
            issues.append("Irregular slice spacing; slices may be missing.")
    return {
        **quality,
        "status": "review" if issues else "pass",
        "issues": issues,
        "slice_count": len(images),
    }


def review_signal(scores: dict[str, float], localization: float | None = None) -> dict:
    """Heuristic flag on uncalibrated scores: low top score or two close classes."""
    ordered = sorted((float(v) for v in scores.values()), reverse=True)
    reasons: list[str] = []
    if ordered and ordered[0] < 0.6:
        reasons.append("Top severity score is below 0.60.")
    if len(ordered) > 1 and ordered[0] - ordered[1] < 0.15:
        reasons.append("Two severity classes have similar scores.")
    if localization is not None and float(localization) < 0.5:
        reasons.append("Localization confidence is below 0.50.")
    return {
        "status": "review" if reasons else "no_flag",
        "reasons": reasons,
        "method": "Uncalibrated score thresholds, for review prioritisation only.",
    }
