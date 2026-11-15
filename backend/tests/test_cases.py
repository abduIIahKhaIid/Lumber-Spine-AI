"""Case library: auth, immutable revisions, finalisation, amended status, exports."""

from fastapi.testclient import TestClient

from app.main import create_app

KEY = {"X-Review-Key": "test-key"}
CASE = {
    "findings": [
        {
            "id": "F1",
            "condition": "SCS",
            "level": "L4/L5",
            "severity": "Severe",
            "scores": {"Normal/Mild": 0.1, "Moderate": 0.2, "Severe": 0.7},
        },
        {"id": "F2", "condition": "SCS", "level": "L5/S1", "severity": "Moderate"},
    ],
    "provenance": {"acquisition": {"condition": "SCS", "plane": "Sagittal", "sequence": "T2"}},
    "comparison_group": "patient-a",
    "label": "Visit 1",
}


def review(revision, finalize=False, decision="accept"):
    return {
        "expected_revision": revision,
        "decisions": [
            {"id": "F1", "decision": decision, "corrected_severity": None, "note": ""},
            {"id": "F2", "decision": "accept", "corrected_severity": None, "note": ""},
        ],
        "impression": "Severe L4/L5 canal stenosis" if finalize else "",
        "finalize": finalize,
    }


def test_auth_required():
    with TestClient(create_app()) as client:
        assert client.get("/api/cases").status_code == 401
        assert client.get("/api/cases", headers={"X-Review-Key": "wrong"}).status_code == 401


def test_review_workflow_and_exports():
    with TestClient(create_app()) as client:
        case_id = client.post("/api/cases", json=CASE, headers=KEY).json()["id"]
        listed = client.get("/api/cases", headers=KEY).json()
        assert listed[0]["comparison_key"] == ["SCS", "Sagittal", "T2"]

        assert (
            client.post(
                f"/api/cases/{case_id}/reviews",
                json=review(0, finalize=True, decision="pending"),
                headers=KEY,
            ).status_code
            == 422
        )
        assert (
            client.post(f"/api/cases/{case_id}/reviews", json=review(0), headers=KEY).json()[
                "revision"
            ]
            == 1
        )
        assert (
            client.post(f"/api/cases/{case_id}/reviews", json=review(0), headers=KEY).status_code
            == 409
        )  # stale write
        client.post(f"/api/cases/{case_id}/reviews", json=review(1, finalize=True), headers=KEY)
        assert client.get(f"/api/cases/{case_id}/fhir", headers=KEY).json()["status"] == "final"

        client.post(f"/api/cases/{case_id}/reviews", json=review(2, finalize=True), headers=KEY)
        fhir = client.get(f"/api/cases/{case_id}/fhir", headers=KEY).json()
        assert fhir["status"] == "amended" and fhir["meta"]["versionId"] == "3"

        pdf = client.get(f"/api/cases/{case_id}/report.pdf", headers=KEY)
        assert pdf.content.startswith(b"%PDF")
        assert client.delete(f"/api/cases/{case_id}", headers=KEY).json() == {"deleted": True}


def test_corrections_need_a_note():
    with TestClient(create_app()) as client:
        case_id = client.post("/api/cases", json=CASE, headers=KEY).json()["id"]
        body = review(0, decision="edit")
        body["decisions"][0]["corrected_severity"] = "Moderate"
        assert (
            client.post(f"/api/cases/{case_id}/reviews", json=body, headers=KEY).status_code == 422
        )


def test_validation_pending_by_default():
    with TestClient(create_app()) as client:
        assert client.get("/api/cases/validation", headers=KEY).json()["status"] == "pending"
