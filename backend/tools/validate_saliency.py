"""Offline Grad-CAM sanity measurements on reviewed, preprocessed inputs.

Run from backend: python -m tools.validate_saliency checkpoint.pth inputs.npz
NPZ contains inputs[N,3,H,W], class_indices[N], matching the model preprocessing.
These measurements require expert interpretation; no automatic clinical pass is claimed.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F


def activation(model, tensor, target):
    captured = {}

    def hook(_module, _args, output):
        captured["features"] = output
        output.register_hook(lambda gradient: captured.update(gradient=gradient))

    handle = model.attn.register_forward_hook(hook)
    try:
        model.zero_grad(set_to_none=True)
        model(tensor.detach().requires_grad_(True))[0, target].backward()
        heat = (
            (captured["features"] * captured["gradient"].mean((2, 3), keepdim=True))
            .sum(1, keepdim=True)
            .relu()
        )
        heat = F.interpolate(heat, size=tensor.shape[-2:], mode="bilinear", align_corners=False)[
            0, 0
        ].detach()
        return heat / heat.max().clamp(min=1e-8)
    finally:
        handle.remove()
        model.zero_grad(set_to_none=True)


def measure(model, tensor, target):
    heat = activation(model, tensor, target)
    randomized = copy.deepcopy(model)
    torch.manual_seed(42)
    for module in randomized.modules():
        if hasattr(module, "reset_parameters"):
            module.reset_parameters()
    randomized.eval()
    random_heat = activation(randomized, tensor, target)
    a, b = heat.flatten().cpu().numpy(), random_heat.flatten().cpu().numpy()
    similarity = float(np.corrcoef(a, b)[0, 1]) if a.std() > 1e-8 and b.std() > 1e-8 else None
    count = max(1, int(heat.numel() * 0.2))
    mask = torch.zeros_like(heat).flatten()
    mask[heat.flatten().topk(count).indices] = 1
    shuffled = mask[torch.randperm(mask.numel())].reshape_as(heat)
    mask = mask.reshape_as(heat)
    baseline = tensor.mean(dim=(2, 3), keepdim=True)
    with torch.no_grad():
        original = float(model(tensor).softmax(1)[0, target])
        salient = float(model(tensor * (1 - mask) + baseline * mask).softmax(1)[0, target])
        random = float(model(tensor * (1 - shuffled) + baseline * shuffled).softmax(1)[0, target])
    return {
        "target": int(target),
        "empty_map": bool(heat.max() <= 1e-8),
        "randomized_weight_correlation": similarity,
        "salient_occlusion_score_drop": original - salient,
        "random_occlusion_score_drop": original - random,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("inputs", type=Path)
    args = parser.parse_args()
    from app.ml.architectures.severity_net import SeverityNet

    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    model = SeverityNet(
        checkpoint.get("backbone", "mobilenetv3_small_100"), len(checkpoint.get("class_names") or checkpoint["classes"])
    )
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    with np.load(args.inputs, allow_pickle=False) as data:
        inputs, targets = data["inputs"], data["class_indices"]
        if (
            inputs.ndim != 4
            or inputs.shape[1] != 3
            or len(inputs) != len(targets)
            or not np.isfinite(inputs).all()
        ):
            raise ValueError("Invalid preprocessed inputs")
        rows = [
            measure(model, torch.tensor(image[None], dtype=torch.float32), int(target))
            for image, target in zip(inputs, targets)
        ]
    output = Path(__file__).resolve().parents[1] / "data" / "saliency.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "status": "measurements_require_review",
                "method": "Grad-CAM ReLU; 20% occlusion; weight randomization",
                "checkpoint_sha256": hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
                "measurements": rows,
            },
            indent=2,
        )
    )
    print(f"Wrote {output}")
