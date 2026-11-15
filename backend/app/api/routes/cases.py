"""Case library: saved analyses, immutable review revisions, reviewed exports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.core.config import get_settings
from app.core.security import authorize
from app.db.database import connect
from app.schemas.cases import Case, Review

router = APIRouter(prefix="/api/cases", tags=["cases"])


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _comparison_key(payload: dict) -> list:
    acquisition = payload.get("provenance", {}).get("acquisition", {})
    return [acquisition.get(k) for k in ("condition", "plane", "sequence")]


@router.get("", dependencies=[Depends(authorize)])
def list_cases():
    with connect() as db:
        rows = db.execute("SELECT * FROM cases ORDER BY created DESC LIMIT 200").fetchall()
        finalized = {
            row["case_id"]
            for row in db.execute(
                "SELECT case_id FROM reviews WHERE json_extract(payload, '$.finalize') = 1"
            )
        }
    return [
        {
            "id": r["id"],
            "created": r["created"],
            "finalized": r["id"] in finalized,
            **json.loads(r["payload"]),
        }
        for r in rows
    ]


@router.post("", dependencies=[Depends(authorize)])
def save_case(case: Case):
    payload = case.model_dump()
    payload["comparison_key"] = _comparison_key(payload)
    if len(json.dumps(payload)) > 60000:
        raise HTTPException(413, "Case summary too large")
    case_id = str(uuid4())
    with connect() as db:
        db.execute("INSERT INTO cases VALUES (?, ?, ?)", (case_id, _now(), json.dumps(payload)))
    return {"id": case_id}


@router.get("/validation", dependencies=[Depends(authorize)])
def validation():
    settings = get_settings()
    path = settings.calibration_file
    result = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.is_file()
        else {
            "status": "pending",
            "message": "Run tools/evaluate.py on held-out labelled predictions. "
            "No measured performance is available yet.",
        }
    )
    saliency = settings.data_dir / "saliency.json"
    if saliency.is_file():
        result["saliency"] = json.loads(saliency.read_text(encoding="utf-8"))
    return result


@router.get("/{case_id}", dependencies=[Depends(authorize)])
def get_case(case_id: str):
    with connect() as db:
        row = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Case not found")
        revisions = [
            {**dict(item), "payload": json.loads(item["payload"])}
            for item in db.execute(
                "SELECT * FROM reviews WHERE case_id=? ORDER BY revision", (case_id,)
            )
        ]
    return {
        "id": case_id,
        "created": row["created"],
        **json.loads(row["payload"]),
        "revisions": revisions,
    }


@router.post("/{case_id}/reviews")
def review_case(case_id: str, review: Review, reviewer: str = Depends(authorize)):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT payload FROM cases WHERE id=?", (case_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Case not found")
        ids = {item["id"] for item in json.loads(row[0])["findings"]}
        submitted = [item.id for item in review.decisions]
        if set(submitted) != ids or len(submitted) != len(ids):
            raise HTTPException(422, "Review must contain each case finding exactly once")
        for decision in review.decisions:
            if decision.decision == "edit" and (
                not decision.corrected_severity or not decision.note.strip()
            ):
                raise HTTPException(422, "Corrections need a severity and an explanation")
        if review.finalize and (
            not ids
            or any(d.decision == "pending" for d in review.decisions)
            or not review.impression.strip()
        ):
            raise HTTPException(422, "Complete every decision and the impression to finalize")
        revision = db.execute(
            "SELECT COALESCE(MAX(revision),0) FROM reviews WHERE case_id=?", (case_id,)
        ).fetchone()[0]
        if revision != review.expected_revision:
            raise HTTPException(409, "A newer revision exists. Reload this case before saving.")
        db.execute(
            "INSERT INTO reviews VALUES (?, ?, ?, ?, ?)",
            (case_id, revision + 1, _now(), reviewer, json.dumps(review.model_dump())),
        )
    return {"revision": revision + 1, "reviewer": reviewer}


@router.delete("/{case_id}", dependencies=[Depends(authorize)])
def delete_case(case_id: str):
    with connect() as db:
        db.execute("DELETE FROM reviews WHERE case_id=?", (case_id,))
        deleted = db.execute("DELETE FROM cases WHERE id=?", (case_id,)).rowcount
    if not deleted:
        raise HTTPException(404, "Case not found")
    return {"deleted": True}


def _status(revisions: list[dict]) -> str:
    finals = [r for r in revisions if r["payload"].get("finalize")]
    if not finals:
        return "preliminary"
    latest = revisions[-1]
    if latest["payload"].get("finalize") and latest["revision"] == finals[0]["revision"]:
        return "final"
    return "amended"


@router.get("/{case_id}/fhir", dependencies=[Depends(authorize)])
def fhir_report(case_id: str):
    case = get_case(case_id)
    revisions = case["revisions"]
    latest = revisions[-1] if revisions else None
    review = latest["payload"] if latest else {}
    status = _status(revisions)
    decisions = {item["id"]: item for item in review.get("decisions", [])}
    observations = []
    for index, finding in enumerate(case["findings"]):
        decision = decisions.get(finding["id"], {})
        if decision.get("decision") == "reject":
            continue
        observations.append(
            {
                "resourceType": "Observation",
                "id": f"finding-{index}",
                "status": status if status != "amended" else "amended",
                "code": {"text": f"{finding['condition']} {finding['level']}"},
                "valueCodeableConcept": {
                    "text": decision.get("corrected_severity")
                    if decision.get("decision") == "edit"
                    else finding["severity"]
                },
            }
        )
    conclusion = review.get("impression", "Awaiting clinician review")
    if review.get("next_review_step"):
        conclusion += "\nNext review step: " + review["next_review_step"]
    return {
        "resourceType": "DiagnosticReport",
        "id": case_id,
        "meta": {"versionId": str(latest["revision"] if latest else 0)},
        "status": status,
        "code": {"text": "Lumbar MRI review"},
        "issued": latest["created"] if latest else case["created"],
        "contained": observations,
        "result": [{"reference": "#" + o["id"]} for o in observations],
        "conclusion": conclusion,
    }


@router.get("/{case_id}/report.pdf", dependencies=[Depends(authorize)])
def case_pdf(case_id: str):
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    case = get_case(case_id)
    report = fhir_report(case_id)
    styles = getSampleStyleSheet()
    lines = [
        f"Case: {case.get('label') or case_id}",
        f"Revision {report['meta']['versionId']} · Status: {report['status']}",
        f"Issued: {report['issued']}",
    ]
    if case["revisions"]:
        lines.append("Reviewer: " + case["revisions"][-1]["reviewer"])
    lines += [
        f"{o['code']['text']}: {o['valueCodeableConcept']['text']}" for o in report["contained"]
    ]
    lines += [
        "Impression: " + report["conclusion"],
        "Model checkpoints: "
        + json.dumps(case.get("provenance", {}).get("checkpoints_sha256", {})),
        "Clinical credentials are not verified by this local application.",
    ]
    elements = [Paragraph("Lumber Spine AI — Reviewed findings", styles["Title"])]
    for line in lines:
        elements += [Paragraph(escape(line), styles["BodyText"]), Spacer(1, 6)]
    output = BytesIO()
    SimpleDocTemplate(output).build(elements)
    return Response(
        output.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="review-{case_id}.pdf"'},
    )
