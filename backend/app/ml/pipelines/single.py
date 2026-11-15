"""Single DICOM slice: YOLO level detection -> severity crop -> SeverityNet -> focus map."""

from __future__ import annotations

import os

from PIL import Image

from app.ml import dicom
from app.ml.pipelines.common import (
    Progress,
    assemble,
    classify_crop,
    finding,
    image_entry,
    noop_progress,
    sort_findings,
)
from app.ml.preprocessing import severity_crop, severity_tensor
from app.ml.provenance import provenance
from app.ml.quality import assess_image
from app.ml.registry import SINGLE_CLASS_MAPS, device, get_registry


def crop_anchor(box) -> tuple[float, float]:
    """Severity crops are centred on the detected level (box centre).

    SINGLE_CROP_ANCHOR=corner restores the earlier top-left behaviour for comparison.
    """
    x1, y1, x2, y2 = (float(v) for v in box)
    if os.getenv("SINGLE_CROP_ANCHOR", "center").lower() == "corner":
        return x1, y1
    return (x1 + x2) / 2, (y1 + y2) / 2


def run_single(data: bytes, progress: Progress = noop_progress) -> dict:
    progress(5, "Reading DICOM")
    dataset = dicom.read_dataset(data)
    lumbar_named = dicom.lumbar_status(dataset)
    info = dicom.classify(dataset)
    condition = dicom.require_supported(info)
    raw = dicom.pixels(dataset)
    photometric = str(getattr(dataset, "PhotometricInterpretation", ""))
    acquisition = {
        "condition": condition,
        "plane": info["plane"],
        "sequence": info["sequence"],
        "dimensions": [int(raw.shape[0]), int(raw.shape[1])],
        "pixel_spacing": [round(float(v), 4) for v in getattr(dataset, "PixelSpacing", [])],
    }
    dicom.deidentify(dataset)

    quality = assess_image(raw)
    if not lumbar_named:
        quality.setdefault("notes", []).append(
            "Lumbar anatomy is not named in the DICOM metadata; confirm the image manually."
        )
    image_u8 = dicom.to_uint8(raw, photometric)

    registry = get_registry()
    progress(20, f"Detecting {dicom.CONDITION_NAMES[condition].lower()} levels")
    detector = registry.yolo(condition)
    results = detector.predict(Image.fromarray(image_u8).convert("RGB"), verbose=False)
    boxes = results[0].boxes
    detections = boxes.data.cpu().numpy() if boxes is not None else []

    best: dict[str, tuple] = {}
    for det in detections:
        x1, y1, x2, y2, conf, cls_id = (float(v) for v in det[:6])
        label = SINGLE_CLASS_MAPS[condition].get(int(cls_id))
        if label and (label not in best or conf > best[label][1]):
            best[label] = ([x1, y1, x2, y2], conf)

    severity = registry.severity(condition)
    if severity.input_slices == "before_center_after":
        raise dicom.UnsupportedScan(
            "This severity checkpoint needs neighbouring slices; use the multi-scan upload."
        )
    findings = []
    total = max(len(best), 1)
    for number, (label, (box, conf)) in enumerate(best.items(), start=1):
        progress(30 + int(55 * number / total), f"Grading {label.replace('_', ' ')}")
        x, y = crop_anchor(box)
        crop = severity_crop(image_u8, x, y)
        scored = classify_crop(severity, severity_tensor(crop).to(device()), crop)
        findings.append(
            finding(
                index=number,
                condition=condition,
                label=label,
                box=box,
                point=[x, y],
                image_index=0,
                slice_number=None,
                scored=scored,
                severity=severity,
                localization=conf,
            )
        )
    sort_findings(findings)
    progress(92, "Preparing results")
    return assemble(
        mode="single",
        info=info,
        findings=findings,
        images=[image_entry(0, image_u8, findings, None)],
        quality=quality,
        provenance=provenance(condition, "single", acquisition),
    )
