"""Grad-CAM focus maps for SeverityNet, tinted with the predicted severity color."""

from __future__ import annotations

import base64
from io import BytesIO
from threading import Lock

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from app.ml.severity import HEX, canonical, color

_lock = Lock()  # hooks + backward on a shared model must not interleave
PREVIEW_SIZE = 224


def png_base64(image: Image.Image) -> str:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def _heat(model, input_tensor: torch.Tensor, class_index: int) -> tuple[np.ndarray | None, str]:
    captured: dict[str, torch.Tensor] = {}

    def capture(_module, _inputs, output):
        captured["features"] = output
        output.register_hook(lambda gradient: captured.__setitem__("gradient", gradient))

    method = "Grad-CAM on the severity classifier's attention block"
    with _lock:
        handle = model.attn.register_forward_hook(capture)
        try:
            with torch.enable_grad():
                model.zero_grad(set_to_none=True)
                logits = model(input_tensor.detach().clone().requires_grad_(True))
                logits[0, class_index].backward()
                features, gradient = captured.get("features"), captured.get("gradient")
                if features is None or gradient is None:
                    return None, "Unavailable"
                weights = gradient.mean(dim=(2, 3), keepdim=True)
                signed = (weights * features).sum(dim=1, keepdim=True)
                heat = F.relu(signed)
                if float(heat.detach().amax()) <= 1e-8:
                    heat = signed.abs()
                    method = "Absolute gradient-weighted activation (fallback)"
                heat = F.interpolate(
                    heat, size=(PREVIEW_SIZE, PREVIEW_SIZE), mode="bilinear", align_corners=False
                )
                result = heat[0, 0].detach().cpu().numpy()
        finally:
            handle.remove()
            model.zero_grad(set_to_none=True)
    peak = float(result.max())
    if not np.isfinite(peak) or peak <= 1e-8:
        return None, method
    return np.clip(result / peak, 0, 1), method


def explain(model, input_tensor: torch.Tensor, class_index: int, crop: Image.Image, severity: str):
    """Return the model crop and a focus overlay colored green/yellow/red by severity."""
    preview = crop.convert("RGB").resize((PREVIEW_SIZE, PREVIEW_SIZE), Image.Resampling.BILINEAR)
    result = {
        "crop_image": png_base64(preview),
        "heatmap_image": None,
        "method": "Unavailable",
        "color": HEX.get(canonical(severity), "#94a3b8"),
        "note": "Highlighted pixels influenced this model score. They do not prove a lesion.",
    }
    try:
        heat, method = _heat(model, input_tensor, class_index)
    except Exception:  # an explanation failure must never fail the prediction
        return result
    result["method"] = method
    if heat is None:
        return result
    source = np.asarray(preview, dtype=np.float32)
    tint = np.empty_like(source)
    tint[...] = color(severity)
    # Only the upper part of the map is tinted so low-sensitivity regions stay readable.
    alpha = (np.clip((heat - 0.25) / 0.75, 0, 1) ** 0.8 * 0.62)[..., None]
    overlay = np.clip(source * (1 - alpha) + tint * alpha, 0, 255).astype(np.uint8)
    result["heatmap_image"] = png_base64(Image.fromarray(overlay))
    return result
