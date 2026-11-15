"""Validated request bodies for the case library."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Severity = Literal["Normal/Mild", "Moderate", "Severe"]


class Finding(BaseModel):
    id: str = Field(max_length=100)
    condition: Literal["SCS", "NFN", "SS"]
    level: str = Field(max_length=40)
    severity: str = Field(max_length=40)
    scores: dict[str, Probability] = Field(default_factory=dict, max_length=3)


class Case(BaseModel):
    findings: list[Finding] = Field(max_length=30)
    provenance: dict = Field(default_factory=dict)
    quality: dict = Field(default_factory=dict)
    # Pseudonymous identifiers chosen by the user; never a patient name.
    comparison_group: str = Field(default="", max_length=80)
    label: str = Field(default="", max_length=80)

    @model_validator(mode="after")
    def unique_findings(self):
        ids = [finding.id for finding in self.findings]
        if len(ids) != len(set(ids)):
            raise ValueError("Each finding must have a unique identifier")
        return self


class Decision(BaseModel):
    id: str = Field(max_length=100)
    decision: Literal["accept", "edit", "reject", "pending"]
    corrected_severity: Severity | None = None
    note: str = Field(default="", max_length=1000)


class Review(BaseModel):
    expected_revision: int = Field(ge=0)
    decisions: list[Decision] = Field(max_length=30)
    impression: str = Field(default="", max_length=4000)
    symptoms: str = Field(default="", max_length=2000)
    next_review_step: str = Field(default="", max_length=2000)
    finalize: bool = False
