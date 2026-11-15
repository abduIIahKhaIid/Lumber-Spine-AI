"""Deterministic, evidence-linked review recommendations.

Each rule turns structured model output into a prioritised next step with a clinician
and a patient wording. Rules are educational review prompts: they never diagnose or
prescribe, and the rule set is versioned so a clinician can approve it explicitly.
"""

from __future__ import annotations

from collections import defaultdict

RULES_VERSION = "2026.11"
RULES_STATUS = "Draft - pending clinician approval"
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
LEVEL_ORDER = ("L1/L2", "L2/L3", "L3/L4", "L4/L5", "L5/S1")


def _item(rule, priority, category, title, clinician, patient, evidence=()):
    return {
        "id": rule,
        "priority": priority,
        "category": category,
        "title": title,
        "clinician": clinician,
        "patient": patient,
        "evidence": list(evidence),
    }


def _where(finding: dict) -> str:
    return f"{finding['level_label']}"


def recommend(result: dict) -> list[dict]:
    findings = result.get("findings", [])
    quality = result.get("quality", {})
    condition = result.get("condition")
    name = result.get("condition_name", condition or "the assessed condition").lower()
    items: list[dict] = []

    severe = [f for f in findings if f["severity"] == "Severe"]
    moderate = [f for f in findings if f["severity"] == "Moderate"]
    significant = severe + moderate

    if severe:
        where = ", ".join(_where(f) for f in severe)
        items.append(
            _item(
                "severe-finding",
                "high",
                "finding",
                f"Prioritise specialist review of severe {name}",
                f"Model graded {name} as severe at {where}. Confirm on the original slices and "
                "correlate with the neurological examination before any management decision.",
                f"The software flagged possible severe narrowing at {where}. Please share this "
                "report with your doctor so they can check the images themselves.",
                [f["id"] for f in severe],
            )
        )

    if condition == "SCS" and severe:
        items.append(
            _item(
                "scs-red-flags",
                "high",
                "safety",
                "Screen for red-flag symptoms",
                "Severe central canal narrowing was suggested. Ask about bladder or bowel "
                "dysfunction, saddle anaesthesia and progressive bilateral leg weakness; these "
                "warrant urgent assessment.",
                "If you notice new problems controlling your bladder or bowels, numbness between "
                "the legs, or worsening weakness in both legs, seek emergency care immediately.",
                [f["id"] for f in severe],
            )
        )

    # Two or more adjacent levels at moderate or worse on the same side.
    by_side: dict[str | None, list[dict]] = defaultdict(list)
    for f in significant:
        by_side[f["side"]].append(f)
    for side, group in by_side.items():
        ranks = sorted(LEVEL_ORDER.index(f["level"]) for f in group)
        if any(b - a == 1 for a, b in zip(ranks, ranks[1:])):
            label = f" ({side})" if side else ""
            items.append(
                _item(
                    f"multilevel-{side or 'central'}",
                    "medium",
                    "finding",
                    f"Multilevel involvement{label}",
                    f"Adjacent levels are graded moderate or severe{label}. Review the levels "
                    "together, since multilevel narrowing changes how symptoms are interpreted.",
                    "More than one neighbouring level shows narrowing. Your doctor will look at "
                    "them together.",
                    [f["id"] for f in group],
                )
            )

    if condition in ("NFN", "SS") and significant:
        for side in ("left", "right"):
            group = [f for f in significant if f["side"] == side]
            if not group:
                continue
            where = ", ".join(f["level"] for f in group)
            nerve = "exiting" if condition == "NFN" else "traversing"
            items.append(
                _item(
                    f"{condition.lower()}-{side}",
                    "medium",
                    "correlation",
                    f"Correlate with {side}-sided leg symptoms",
                    f"{name.capitalize()} at {side} {where} may affect the {nerve} nerve root. "
                    f"Compare with the {side} dermatomal distribution of pain, numbness or "
                    "weakness.",
                    f"Narrowing was suggested on the {side} side at {where}. Tell your doctor "
                    f"if you have pain, tingling or weakness in your {side} leg.",
                    [f["id"] for f in group],
                )
            )

    flagged = [f for f in findings if f.get("uncertainty", {}).get("status") == "review"]
    if flagged:
        items.append(
            _item(
                "low-confidence",
                "medium",
                "uncertainty",
                "Verify low-confidence predictions",
                f"{len(flagged)} prediction(s) have a low or closely contested score. Review "
                "these levels on the original slices before relying on the grade.",
                "Some results are less certain. A doctor should double-check them.",
                [f["id"] for f in flagged],
            )
        )

    if quality.get("status") == "review":
        issues = quality.get("issues", [])
        items.append(
            _item(
                "image-quality",
                "medium",
                "quality",
                "Check image quality flags",
                "Automated input checks raised: "
                + "; ".join(issues[:4])
                + ". Consider repeat or additional sequences if the images are not diagnostic.",
                "The software noticed possible issues with the images, so results may be less "
                "reliable.",
            )
        )

    not_assessed = result.get("summary", {}).get("not_assessed", [])
    if not_assessed:
        items.append(
            _item(
                "not-assessed",
                "low",
                "coverage",
                "Some levels were not assessed",
                "No prediction was produced for "
                + ", ".join(not_assessed)
                + ". Absence of a finding does not exclude pathology.",
                "A few spine levels could not be checked automatically.",
            )
        )

    if findings and not significant:
        items.append(
            _item(
                "no-significant",
                "low",
                "finding",
                "No moderate or severe model findings",
                f"All assessed levels were graded normal/mild for {name}. This does not exclude "
                "other conditions or sequences that were not analysed.",
                "The software did not flag moderate or severe narrowing in this series.",
            )
        )
    if not findings:
        items.append(
            _item(
                "no-detections",
                "medium",
                "coverage",
                "No levels were detected",
                "The model returned no level detections. Check that the image shows the lumbar "
                "spine in the expected plane and sequence.",
                "The software could not find spine levels in this image.",
            )
        )

    items.append(
        _item(
            "clinical-correlation",
            "low",
            "next-step",
            "Discuss results with a clinician",
            "Interpret model output alongside history, examination and the radiologist's read.",
            "These results are an aid, not a diagnosis. Discuss them with your doctor together "
            "with your symptoms.",
        )
    )
    items.sort(key=lambda item: PRIORITY_ORDER[item["priority"]])
    for item in items:
        item["rules_version"] = RULES_VERSION
    return items
