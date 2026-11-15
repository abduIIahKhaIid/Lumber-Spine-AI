import numpy as np
import pytest

from tools.evaluate import evaluate, metrics


def test_metrics_include_balanced_scores_and_rsna_loss():
    labels = np.array([0, 0, 1, 2])
    scores = np.array([[0.9, 0.05, 0.05], [0.8, 0.1, 0.1], [0.2, 0.7, 0.1], [0.6, 0.2, 0.2]])
    result = metrics(labels, scores)
    assert result["accuracy"] == 0.75
    assert result["per_class"]["Severe"]["recall"] == 0.0
    assert result["balanced_accuracy"] == pytest.approx(2 / 3)
    assert result["rsna_weighted_log_loss"] > 0


def row(case, split, label, scores):
    return {
        "case_id": case,
        "split": split,
        "condition": "SCS",
        "label": str(label),
        "normal_mild": str(scores[0]),
        "moderate": str(scores[1]),
        "severe": str(scores[2]),
    }


def test_evaluate_requires_disjoint_splits():
    rows = [row("a", "calibration", 0, (0.8, 0.1, 0.1)), row("a", "test", 1, (0.2, 0.7, 0.1))]
    with pytest.raises(ValueError):
        evaluate(rows, "demo")
    rows[1]["case_id"] = "b"
    result = evaluate(rows, "demo")
    assert result["conditions"]["SCS"]["raw"]["count"] == 1
