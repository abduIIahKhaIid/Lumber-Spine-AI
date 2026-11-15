"use client";

import { useEffect, useRef, useState } from "react";
import { api, jsonBody } from "@/lib/api";
import { getReviewKey, setReviewKey } from "@/features/cases/review-key";
import type { AnalysisResult } from "./types";

export default function SaveCaseDialog({
  result,
  onClose,
}: {
  result: AnalysisResult;
  onClose: (message?: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [key, setKey] = useState("");
  const [label, setLabel] = useState("");
  const [group, setGroup] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setKey(getReviewKey());
    dialog.current?.showModal();
  }, []);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(
        "/api/cases",
        jsonBody(
          {
            findings: result.findings.map((f) => ({
              id: f.id,
              condition: f.condition,
              level: f.level_label,
              severity: f.severity,
              scores: f.class_scores,
            })),
            provenance: result.provenance,
            quality: { status: result.quality.status, issues: result.quality.issues },
            comparison_group: group.trim(),
            label: label.trim(),
          },
          { "X-Review-Key": key },
        ),
      );
      setReviewKey(key);
      onClose("Saved. Open Cases to review the findings and prepare a signed-off report.");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={dialog}
      onClose={() => onClose()}
      className="m-auto w-[min(32rem,calc(100%-2rem))] rounded-2xl border border-rule p-0 backdrop:bg-ink/40"
    >
      <form onSubmit={save} className="space-y-4 p-6">
        <h2 className="text-xl font-bold">Save to cases</h2>
        <p className="text-sm text-graphite">
          Saves the structured findings only, never the images. Use a pseudonymous label, not a
          patient name.
        </p>
        <label className="block text-sm font-semibold">
          Case label
          <input
            className="field mt-1"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            maxLength={80}
            placeholder="Study 014, follow-up"
          />
        </label>
        <label className="block text-sm font-semibold">
          Comparison group
          <input
            className="field mt-1"
            value={group}
            onChange={(e) => setGroup(e.target.value)}
            maxLength={80}
            placeholder="Same value for scans of the same person"
          />
        </label>
        <label className="block text-sm font-semibold">
          Review access key
          <input
            className="field mt-1"
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            required
            autoComplete="off"
          />
          <span className="mt-1 block text-xs font-normal text-graphite">
            REVIEW_ACCESS_TOKEN from backend/.env. Kept for this browser tab only.
          </span>
        </label>
        {error && (
          <p role="alert" className="rounded-lg bg-sev-severe/10 p-3 text-sm text-sev-severe-ink">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-quiet" onClick={() => onClose()}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy || !key}>
            Save case
          </button>
        </div>
      </form>
    </dialog>
  );
}
