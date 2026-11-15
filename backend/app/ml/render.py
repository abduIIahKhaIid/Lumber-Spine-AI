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


def _area(a, b, gap=0) -> float:
    w = min(a[2], b[2]) + gap - max(a[0], b[0])
    h = min(a[3], b[3]) + gap - max(a[1], b[1])
    return max(0, w) * max(0, h)


def place_labels(
    findings: list[dict], sizes: list[tuple[int, int]], width: int, height: int, pad: int
) -> list[tuple[int, int]]:
    """Top-left corner for each label, avoiding other labels and every level box.

    Radiological convention puts the patient's right on the viewer's left, so labels of
    right-side levels prefer the left of their box and left-side labels the right.
    Each label tries its preferred side, then the other sides, then shifted rows; if
    nothing is free the position with the least overlap wins.
    """
    gap = max(2, pad // 2)
    boxes = [tuple(f["box"]) for f in findings]
    placed: list[tuple[float, float, float, float]] = []
    result: list[tuple[int, int]] = [(0, 0)] * len(findings)
    order = sorted(range(len(findings)), key=lambda i: (boxes[i][1], boxes[i][0]))
    for i in order:
        x0, y0, x1, y1 = boxes[i]
        w, h = sizes[i]
        cy = (y0 + y1) / 2 - h / 2
        left = (x0 - pad - w, cy)
        right = (x1 + pad, cy)
        above = ((x0 + x1) / 2 - w / 2, y0 - pad - h)
        below = ((x0 + x1) / 2 - w / 2, y1 + pad)
        side = findings[i].get("side")
        anchors = (
            [left, above, below, right]
            if side == "right"
            else [right, above, below, left]
            if side == "left"
            else [right, left, above, below]
        )
        best, best_cost = None, None
        for step in range(0, 7):
            for ax, ay in anchors:
                for dy in (0,) if step == 0 else (step * (h + gap), -step * (h + gap)):
                    x = min(max(0, ax), width - w)
                    y = min(max(0, ay + dy), height - h)
                    rect = (x, y, x + w, y + h)
                    cost = sum(_area(rect, o, gap) for o in placed) * 4 + sum(
                        _area(rect, b) for b in boxes
                    )
                    cost += abs(dy) * 0.01 + (x != ax) * 0.5
                    if best_cost is None or cost < best_cost:
                        best, best_cost = rect, cost
            if best_cost is not None and best_cost < 1:
                break
        placed.append(best)
        result[i] = (int(best[0]), int(best[1]))
    return result


def annotate(image: np.ndarray, findings: list[dict], title: str | None = None) -> Image.Image:
    """Draw severity-colored boxes with non-overlapping level/severity labels."""
    canvas = Image.fromarray(image).convert("RGB")
    width, height = canvas.size
    scale = max(1.0, min(width, height) / 512)
    draw = ImageDraw.Draw(canvas, "RGBA")
    font = _font(int(13 * scale))
    line = max(3, int(3 * scale))
    pad = int(4 * scale)

    labels, sizes = [], []
    for finding in findings:
        text = finding["level_label"]  # the box/label color carries the grade
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        labels.append((text, top))
        sizes.append((right - left + 2 * pad, bottom - top + 2 * pad))
    positions = place_labels(findings, sizes, width, height, pad)

    for finding in findings:
        x0, y0, x1, y1 = finding["box"]
        rgb = color(finding["severity"])
        draw.rectangle([x0, y0, x1, y1], fill=(*rgb, 38), outline=(*rgb, 255), width=line)
    for finding, (text, top), (w, h), (lx, ly) in zip(findings, labels, sizes, positions):
        x0, y0, x1, y1 = finding["box"]
        rgb = color(finding["severity"])
        # Leader line from the label edge nearest the box to the box edge, when detached.
        lcx, lcy = lx + w / 2, ly + h / 2
        bx = min(max(lcx, x0), x1)
        by = min(max(lcy, y0), y1)
        ex = min(max(bx, lx), lx + w)
        ey = min(max(by, ly), ly + h)
        if abs(ex - bx) + abs(ey - by) > pad * 2:
            draw.line([(ex, ey), (bx, by)], fill=(*rgb, 255), width=max(2, line - 1))
        draw.rounded_rectangle([lx, ly, lx + w, ly + h], radius=pad, fill=(*rgb, 240))
        draw.text((lx + pad, ly + pad - top), text, fill=(15, 23, 42), font=font)
    if title:
        left, top, right, bottom = draw.textbbox((0, 0), title, font=font)
        draw.rectangle([0, 0, right - left + 12, bottom - top + 10], fill=(2, 6, 23, 200))
        draw.text((6, 5 - top), title, fill=(255, 255, 255), font=font)
    return canvas
