"""PDF report regression: many findings with images and focus maps must lay out."""

import base64
from io import BytesIO

import numpy as np
from PIL import Image

from app.ml.render import annotate
from app.services.recommendations.engine import recommend
from app.services.reports.scan_report import build_scan_report
from tests.conftest import make_finding


def png(width, height):
    buffer = BytesIO()
    Image.fromarray((np.random.rand(height, width) * 255).astype(np.uint8)).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_ten_level_report_with_focus_maps_builds():
    findings = []
    for side in ("left", "right"):
        for level in ("L1/L2", "L2/L3", "L3/L4", "L4/L5", "L5/S1"):
            item = make_finding(f"F{len(findings) + 1}", level, "Moderate", side, "SS")
            item["explanation"]["heatmap_image"] = png(224, 224)
            item["image_index"] = len(findings) % 3
            findings.append(item)
    slice_ = (np.random.rand(320, 320) * 255).astype(np.uint8)
    images = []
    for index in range(3):
        drawn = [f for f in findings if f["image_index"] == index]
        buffer = BytesIO()
        annotate(slice_, drawn, f"Slice {index + 1}").save(buffer, "PNG")
        images.append(
            {
                "index": index,
                "slice_number": index + 1,
                "annotated": base64.b64encode(buffer.getvalue()).decode(),
            }
        )
    result = {
        "analysis_id": "x",
        "mode": "multi",
        "condition": "SS",
        "condition_name": "Subarticular stenosis",
        "plane": "Axial",
        "sequence": "T2",
        "slice_count": 47,
        "images": images,
        "findings": findings,
        "summary": {"counts": {"Moderate": 10}, "flagged": 0, "not_assessed": []},
        "quality": {"status": "pass", "issues": []},
        "provenance": {"pipeline_version": "3.0.0"},
        "created_at": "2026-11-16T00:00:00+00:00",
    }
    result["recommendations"] = recommend(result)
    pdf = build_scan_report(result, "Case 1")
    assert pdf.startswith(b"%PDF") and len(pdf) > 10_000
