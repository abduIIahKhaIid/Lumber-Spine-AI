from app.services.recommendations.engine import recommend
from tests.conftest import make_finding


def ids(items):
    return [item["id"] for item in items]


def test_severe_scs_raises_high_priority_and_red_flags(sample_result):
    items = sample_result["recommendations"]
    assert items[0]["priority"] == "high"
    assert {"severe-finding", "scs-red-flags"} <= set(ids(items))
    severe = next(i for i in items if i["id"] == "severe-finding")
    assert severe["evidence"] == ["F2"]
    assert severe["clinician"] and severe["patient"]


def test_multilevel_low_confidence_and_coverage(sample_result):
    found = ids(sample_result["recommendations"])
    assert "multilevel-central" in found
    assert "low-confidence" in found
    assert "not-assessed" in found
    assert found[-1] == "clinical-correlation" or "clinical-correlation" in found


def test_sided_nfn_correlation_and_all_normal():
    result = {
        "condition": "NFN",
        "condition_name": "Neural foraminal narrowing",
        "findings": [make_finding("F1", "L4/L5", "Moderate", side="left", condition="NFN")],
        "quality": {"status": "review", "issues": ["Low edge detail"]},
        "summary": {"not_assessed": []},
    }
    found = ids(recommend(result))
    assert "nfn-left" in found and "image-quality" in found

    normal = dict(result, findings=[make_finding("F1", "L4/L5", "Normal/Mild", side="left")])
    normal["quality"] = {"status": "pass", "issues": []}
    assert "no-significant" in ids(recommend(normal))


def test_priorities_are_sorted(sample_result):
    order = {"high": 0, "medium": 1, "low": 2}
    ranks = [order[i["priority"]] for i in sample_result["recommendations"]]
    assert ranks == sorted(ranks)
