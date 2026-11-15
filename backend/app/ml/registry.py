"""Loads each checkpoint once per process and keeps it in memory.

The Celery worker (or the in-process job runner) is the only place models live; the
API process never imports torch when Celery is in use.
"""

from __future__ import annotations

import logging
import os
import pickle  # nosec B403
import threading
from dataclasses import dataclass
from pathlib import Path

import torch

from app.core.config import get_settings
from app.ml.architectures.severity_net import SeverityNet
from app.ml.severity import ORDER, canonical

log = logging.getLogger(__name__)

LEVELS = ("L1/L2", "L2/L3", "L3/L4", "L4/L5", "L5/S1")
_SIDED = {
    i: f"{side}_{level}"
    for i, (side, level) in enumerate((side, level) for side in ("L", "R") for level in LEVELS)
}
# YOLO class index -> level label used by the single-image detectors.
SINGLE_CLASS_MAPS = {"SCS": dict(enumerate(LEVELS)), "NFN": _SIDED, "SS": dict(_SIDED)}

# Checkpoints store lowercase class names in this order.
DEFAULT_SEVERITY_CLASSES = ["Moderate", "Normal/Mild", "Severe"]


class ModelUnavailable(RuntimeError):
    pass


@dataclass
class SeverityModel:
    model: SeverityNet
    classes: list[str]
    checkpoint: dict

    @property
    def input_slices(self):
        return self.checkpoint.get("input_slices")


def load_checkpoint(path: Path, map_location) -> dict:
    """Safe tensor-only loading. Pickled code objects are refused unless explicitly allowed."""
    try:
        return torch.load(path, map_location=map_location, weights_only=True)
    except pickle.UnpicklingError as exc:
        if os.getenv("ALLOW_UNSAFE_CHECKPOINTS") == "1":
            log.warning(
                "loading %s with weights_only=False (ALLOW_UNSAFE_CHECKPOINTS=1)", path.name
            )
            return torch.load(path, map_location=map_location, weights_only=False)  # nosec B614
        raise ModelUnavailable(
            f"{path.name} contains non-tensor objects. Re-save it as a plain state dict, or set "
            "ALLOW_UNSAFE_CHECKPOINTS=1 if you trust the file."
        ) from exc


def device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class ModelRegistry:
    def __init__(self, model_dir: Path | None = None):
        self.model_dir = model_dir or get_settings().model_dir
        self._cache: dict[tuple[str, str], object] = {}
        self._lock = threading.Lock()

    def _path(self, name: str) -> Path:
        path = self.model_dir / name
        if not path.is_file():
            raise ModelUnavailable(
                f"Model file {name} is missing. Place the checkpoints in {self.model_dir}."
            )
        return path

    def _get(self, key: tuple[str, str], loader):
        with self._lock:
            if key not in self._cache:
                log.info("loading model %s/%s", *key)
                self._cache[key] = loader()
            return self._cache[key]

    def yolo(self, condition: str):
        def load():
            from ultralytics import YOLO

            return YOLO(str(self._path(f"best_{condition.lower()}.pt")))

        return self._get(("yolo", condition), load)

    def severity(self, condition: str) -> SeverityModel:
        def load():
            checkpoint = load_checkpoint(
                self._path(f"severity_model_full_{condition.lower()}.pth"), device()
            )
            raw = checkpoint.get("class_names") or checkpoint.get("classes")
            classes = [canonical(name) for name in raw] if raw else DEFAULT_SEVERITY_CLASSES
            if sorted(classes) != sorted(ORDER):
                raise ModelUnavailable(f"Unexpected severity classes in checkpoint: {classes}")
            model = SeverityNet(
                model_name=checkpoint.get("backbone", "mobilenetv3_small_100"),
                num_classes=len(classes),
            )
            model.load_state_dict(checkpoint["model_state_dict"], strict=True)
            model.to(device()).eval()
            checkpoint.pop("optimizer_state_dict", None)
            checkpoint.pop("model_state_dict", None)
            return SeverityModel(model, classes, checkpoint)

        return self._get(("severity", condition), load)

    def stage1(self, condition: str):
        def load():
            from app.ml.architectures.stage1 import Spine3DMobileNetV3
            from app.ml.architectures.stage1_medicalnet import MedicalNetResNet10XYZ

            checkpoint = load_checkpoint(self._path(f"stage1_{condition.lower()}.pt"), "cpu")
            architecture = checkpoint.get("architecture", "Spine3DMobileNetV3")
            if architecture == "MedicalNetResNet10XYZ":
                model = MedicalNetResNet10XYZ(condition=condition.lower(), pretrained=False)
            elif architecture == "Spine3DMobileNetV3":
                model = Spine3DMobileNetV3(condition=condition.lower())
            else:
                raise ModelUnavailable(f"Unsupported Stage 1 architecture: {architecture}")
            model.load_state_dict(checkpoint["model_state_dict"], strict=True)
            model.to(device()).eval()
            meta = {k: v for k, v in checkpoint.items() if not k.endswith("state_dict")}
            meta["architecture"] = architecture
            return model, meta

        return self._get(("stage1", condition), load)

    def stage2(self, condition: str):
        def load():
            from app.ml.architectures.stage2 import (
                EfficientNetV2NFN,
                EfficientNetV2SCS,
                EfficientNetV2SS,
            )

            model = {"SCS": EfficientNetV2SCS, "NFN": EfficientNetV2NFN, "SS": EfficientNetV2SS}[
                condition
            ]()
            checkpoint = load_checkpoint(self._path(f"stage2_{condition.lower()}.pt"), "cpu")
            model.load_state_dict(checkpoint["model_state_dict"], strict=True)
            model.to(device()).eval()
            meta = {k: v for k, v in checkpoint.items() if not k.endswith("state_dict")}
            return model, meta

        return self._get(("stage2", condition), load)

    def preload(self) -> None:
        """Best-effort warm-up for worker start; missing files are reported, not fatal."""
        for condition in ("SCS", "NFN", "SS"):
            for loader in (self.yolo, self.severity, self.stage1, self.stage2):
                try:
                    loader(condition)
                except Exception as exc:  # noqa: BLE001 - keep worker alive, report it
                    log.warning("preload %s %s skipped: %s", loader.__name__, condition, exc)


_registry: ModelRegistry | None = None


def get_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry
