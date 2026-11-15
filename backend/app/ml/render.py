"""Annotated slice rendering for reports and downloads (the UI draws its own overlays)."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.ml.severity import color


def box_half_size(width: int, height: int) -> int:
    """Box half-size scaled to the image: ~24 px on a 512 px slice, never below 16 px."""
    return max(16, round(min(width, height) * 0.047))


def point_box(x: float, y: float, width: int, height: int) -> list[int]:
    half = box_half_size(width, height)
    return [
        int(max(0, x - half)),
        int(max(0, y - half)),
        int(min(width - 1, x + half)),
        int(min(height - 1, y + half)),
    ]


def _font(size: int):
    for name in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def annotate(image: np.ndarray, findings: list[dict], title: str | None = None) -> Image.Image:
    """Draw severity-colored boxes with level/severity labels on a uint8 grayscale slice."""
    canvas = Image.fromarray(image).convert("RGB")
    width, height = canvas.size
    scale = max(1.0, min(width, height) / 512)
    draw = ImageDraw.Draw(canvas, "RGBA")
    font = _font(int(13 * scale))
    line = max(3, int(3 * scale))
    for finding in findings:
        x0, y0, x1, y1 = finding["box"]
        rgb = color(finding["severity"])
        draw.rectangle([x0, y0, x1, y1], fill=(*rgb, 38), outline=(*rgb, 255), width=line)
        label = f"{finding['level_label']} · {finding['severity']}"
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
        pad = int(4 * scale)
        tw, th = right - left, bottom - top
        lx = min(max(0, x1 + pad), width - tw - 2 * pad)
        ly = min(max(0, y0), height - th - 2 * pad)
        draw.rounded_rectangle(
            [lx, ly, lx + tw + 2 * pad, ly + th + 2 * pad], radius=pad, fill=(*rgb, 235)
        )
        draw.text((lx + pad, ly + pad - top), label, fill=(15, 23, 42), font=font)
    if title:
        left, top, right, bottom = draw.textbbox((0, 0), title, font=font)
        draw.rectangle([0, 0, right - left + 12, bottom - top + 10], fill=(2, 6, 23, 200))
        draw.text((6, 5 - top), title, fill=(255, 255, 255), font=font)
    return canvas
