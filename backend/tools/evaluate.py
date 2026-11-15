"""Evaluate held-out predictions. CSV: case_id,split,condition,label,normal_mild,moderate,severe.

split must be calibration or test; cases must never overlap. label is 0,1,2.
Run from backend: python tools/evaluate.py predictions.csv --dataset "dataset/version"
This fits temperature on calibration rows and reports metrics on test rows only.
It does not establish clinical validity or change inference automatically.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

CLASS_ORDER = ("Normal/Mild", "Moderate", "Severe")


def probabilities(scores, temperature):
    logits = np.log(np.clip(scores, 1e-12, 1)) / temperature
    exps = np.exp(logits - logits.max(axis=1, keepdims=True))
    return exps / exps.sum(axis=1, keepdims=True)


def metrics(labels, scores):
    predicted = scores.argmax(axis=1)
    confusion = np.zeros((3, 3), dtype=int)
    np.add.at(confusion, (labels, predicted), 1)
    confidence = scores.max(axis=1)
    correct = predicted == labels
    ece = 0.0
    bins = []
    for low in np.arange(0, 1, 0.1):
        mask = (confidence >= low) & (confidence < low + 0.1 + (1e-9 if low > 0.89 else 0))
        if mask.any():
            accuracy, mean = float(correct[mask].mean()), float(confidence[mask].mean())
            ece += float(mask.mean()) * abs(accuracy - mean)
            bins.append({"count": int(mask.sum()), "confidence": mean, "accuracy": accuracy})
    per_class = {}
    for index, name in enumerate(CLASS_ORDER):
        tp = int(confusion[index, index])
        fn = int(confusion[index].sum() - tp)
        fp = int(confusion[:, index].sum() - tp)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[name] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": int(confusion[index].sum()),
        }
    supported = [v for v in per_class.values() if v["support"]]
    # RSNA 2024 competition metric: sample-weighted log loss, weights 1/2/4 by true class.
    weights = np.array([1.0, 2.0, 4.0])[labels]
    picked = np.clip(scores[np.arange(len(labels)), labels], 1e-15, 1)
    weighted_log_loss = float(-(weights * np.log(picked)).sum() / weights.sum())
    return {
        "count": len(labels),
        "accuracy": float(correct.mean()),
        "balanced_accuracy": float(np.mean([v["recall"] for v in supported])) if supported else 0.0,
        "macro_f1": float(np.mean([v["f1"] for v in supported])) if supported else 0.0,
        "per_class": per_class,
        "rsna_weighted_log_loss": weighted_log_loss,
        "confusion_matrix": confusion.tolist(),
        "class_order": list(CLASS_ORDER),
        "ece": ece,
        "brier": float(((scores - np.eye(3)[labels]) ** 2).sum(axis=1).mean()),
        "reliability_bins": bins,
    }


def evaluate(rows, dataset):
    if not rows or any(row["split"] not in ("calibration", "test") for row in rows):
        raise ValueError("Use explicitly separated calibration and test rows")
    groups = {
        split: {r["case_id"] for r in rows if r["split"] == split}
        for split in ("calibration", "test")
    }
    if not all(groups.values()) or groups["calibration"] & groups["test"]:
        raise ValueError("Nonempty disjoint patient/case groups are required")
    result = {
        "status": "measured",
        "dataset": dataset,
        "saliency": "not validated",
        "conditions": {},
    }
    for condition in sorted({r["condition"] for r in rows}):
        subsets = {}
        for split in groups:
            selected = [r for r in rows if r["condition"] == condition and r["split"] == split]
            labels = np.array([int(r["label"]) for r in selected])
            scores = np.array(
                [[float(r[k]) for k in ("normal_mild", "moderate", "severe")] for r in selected]
            )
            if (
                not selected
                or not np.isfinite(scores).all()
                or (scores < 0).any()
                or (scores > 1).any()
                or not np.allclose(scores.sum(axis=1), 1, atol=0.002)
                or not np.isin(labels, [0, 1, 2]).all()
            ):
                raise ValueError(f"Invalid scores or missing split for {condition}")
            subsets[split] = labels, scores
        labels, scores = subsets["calibration"]
        candidates = np.geomspace(0.1, 10, 200)
        losses = [
            -np.log(probabilities(scores, t)[np.arange(len(labels)), labels]).mean()
            for t in candidates
        ]
        temperature = float(candidates[int(np.argmin(losses))])
        test_labels, test_scores = subsets["test"]
        result["conditions"][condition] = {
            "temperature": temperature,
            "calibration_cases": len(groups["calibration"]),
            "raw": metrics(test_labels, test_scores),
            "calibrated": metrics(test_labels, probabilities(test_scores, temperature)),
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--dataset", required=True)
    parser.add_argument(
        "--checkpoint",
        action="append",
        default=[],
        help="CONDITION=path to the exact severity checkpoint used to make the CSV scores",
    )
    parser.add_argument(
        "--approved-by",
        default="",
        help="Reviewer approving deployment after evaluating the results; omit for evaluation only",
    )
    args = parser.parse_args()
    with args.csv.open(newline="", encoding="utf-8-sig") as stream:
        result = evaluate(list(csv.DictReader(stream)), args.dataset)
    result["input_sha256"] = hashlib.sha256(args.csv.read_bytes()).hexdigest()
    for item in args.checkpoint:
        condition, checkpoint_path = item.split("=", 1)
        if condition not in result["conditions"]:
            raise ValueError("Checkpoint condition has no evaluation results")
        result["conditions"][condition]["checkpoint_sha256"] = hashlib.sha256(
            Path(checkpoint_path).read_bytes()
        ).hexdigest()
    if args.approved_by:
        if any(not record.get("checkpoint_sha256") for record in result["conditions"].values()):
            raise ValueError(
                "Every condition needs its exact checkpoint fingerprint before deployment approval"
            )
        result["deployment_approved_by"] = args.approved_by
    target = Path(__file__).resolve().parents[1] / "data" / "validation.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Saved measured validation results to {target}")
