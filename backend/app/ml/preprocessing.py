"""Model input preparation. Every crop is taken from a percentile-windowed uint8 slice."""

from __future__ import annotations

import cv2
import numpy as np
import torch
from PIL import Image
from torchvision import transforms

from app.ml.dicom import to_uint8

# Severity crop window around a level point (pixels on the source slice).
LEFT, RIGHT, UPPER, LOWER = 96, 32, 40, 40
SEVERITY_SIZE = 224

_MEAN = torch.tensor([0.485, 0.456, 0.406], dtype=torch.float32).view(3, 1, 1)
_STD = torch.tensor([0.229, 0.224, 0.225], dtype=torch.float32).view(3, 1, 1)
_to_tensor = transforms.Compose(
    [transforms.Resize((SEVERITY_SIZE, SEVERITY_SIZE)), transforms.ToTensor()]
)


def severity_crop(image_u8: np.ndarray, x: float, y: float) -> Image.Image:
    height, width = image_u8.shape[:2]
    x1, x2 = max(0, int(x - LEFT)), min(width, int(x + RIGHT))
    y1, y2 = max(0, int(y - UPPER)), min(height, int(y + LOWER))
    crop = image_u8[y1:y2, x1:x2]
    if crop.size == 0:
        crop = np.zeros((UPPER + LOWER, LEFT + RIGHT), dtype=np.uint8)
    return Image.fromarray(crop).convert("RGB")


def severity_tensor(crop: Image.Image) -> torch.Tensor:
    """[1, 3, 224, 224] in 0-1, matching the single-slice checkpoints' training input."""
    return _to_tensor(crop).unsqueeze(0)


def stage_normalize(x: torch.Tensor) -> torch.Tensor:
    """Percentile 1-99 scaling of a float tensor to 0-1 (Stage 1 / SS Stage 2 input)."""
    upper, lower = torch.quantile(x.flatten().float(), torch.tensor([0.99, 0.01]))
    x = torch.clip(x, lower, upper)
    return (x - lower) / (upper - lower + 1e-6)


def scs_nfn_normalize(x: np.ndarray) -> np.ndarray:
    lower, upper = np.percentile(x, (1, 99))
    x = np.clip(x.astype(np.float32), lower, upper) - lower
    peak = float(x.max())
    return x / peak if peak > 0 else x


# ---- 2.5D (before/center/after) checkpoints --------------------------------------------


def _fixed_crop(image: np.ndarray, x, y, crop, image_size) -> np.ndarray:
    left, right, upper, lower = crop
    height, width = image.shape
    x0, x1 = int(x - left), int(x + right)
    y0, y1 = int(y - upper), int(y + lower)
    out = np.zeros((upper + lower, left + right), dtype=np.uint8)
    sx0, sx1, sy0, sy1 = max(x0, 0), min(x1, width), max(y0, 0), min(y1, height)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0 : sy1 - y0, sx0 - x0 : sx1 - x0] = image[sy0:sy1, sx0:sx1]
    return cv2.resize(out, (image_size, image_size), interpolation=cv2.INTER_LINEAR)


def preprocess_2p5d_crop(images, records, center_index, x, y, crop, image_size) -> torch.Tensor:
    """[1, 3, H, W] from before/center/after slices of the same series, ImageNet-normalised."""
    center = records[center_index]
    indices = sorted(
        (i for i, row in enumerate(records) if row["series_uid"] == center["series_uid"]),
        key=lambda i: records[i]["instance_number"],
    )
    position = indices.index(center_index)
    selected = [indices[min(max(position + d, 0), len(indices) - 1)] for d in (-1, 0, 1)]
    channels = [
        _fixed_crop(to_uint8(images[i], records[i]["photometric"]), x, y, crop, image_size)
        for i in selected
    ]
    tensor = torch.from_numpy(np.ascontiguousarray(np.stack(channels))).float().div_(255)
    return ((tensor - _MEAN) / _STD).unsqueeze(0)


def bounded_slice(index: float, count: int) -> int:
    if count < 1 or not np.isfinite(float(index)):
        raise ValueError("A finite slice position and nonempty volume are required")
    return min(max(int(index), 0), count - 1)


def neighboring_slices(index: float, count: int) -> tuple[int, int, int]:
    center = bounded_slice(index, count)
    return tuple(bounded_slice(center + offset, count) for offset in (-1, 0, 1))
