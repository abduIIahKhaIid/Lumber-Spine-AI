"""Model-level checks. Architecture tests always run; real-checkpoint tests need MODEL_DIR."""

import os
from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image

from app.ml.architectures.severity_net import SeverityNet
from app.ml.explain import explain
from app.ml.render import annotate, point_box
from app.ml.severity import HEX


def test_severity_net_and_focus_map_color_follows_severity():
    model = SeverityNet().eval()
    tensor = torch.rand(1, 3, 224, 224)
    assert model(tensor).shape == (1, 3)
    crop = Image.fromarray((np.random.rand(80, 128) * 255).astype(np.uint8)).convert("RGB")
    for severity in ("Normal/Mild", "Moderate", "Severe"):
        result = explain(model, tensor, 0, crop, severity)
        assert result["color"] == HEX[severity]
        assert result["crop_image"]


def test_boxes_scale_with_image_and_are_drawn_in_severity_color():
    box = point_box(256, 256, 512, 512)
    assert box[2] - box[0] >= 44  # the old fixed box was 20 px wide
    image = np.zeros((512, 512), dtype=np.uint8)
    finding = {"box": box, "severity": "Severe", "level_label": "L4/L5"}
    rendered = np.asarray(annotate(image, [finding]))
    assert tuple(rendered[box[1], box[0] + 10]) == (239, 68, 68)


MODEL_DIR = Path(os.getenv("MODEL_DIR", Path(__file__).resolve().parents[1] / "model"))
SAMPLE = os.getenv("SAMPLE_SERIES_ZIP")


@pytest.mark.models
@pytest.mark.skipif(
    not (SAMPLE and (MODEL_DIR / "stage2_scs.pt").is_file()),
    reason="set MODEL_DIR and SAMPLE_SERIES_ZIP to run against real checkpoints",
)
def test_real_series_end_to_end():
    from app.ml.pipelines.series import run_series

    result = run_series(Path(SAMPLE).read_bytes())
    assert result["findings"] and result["images"]
    assert all(f["severity"] in ("Normal/Mild", "Moderate", "Severe") for f in result["findings"])
