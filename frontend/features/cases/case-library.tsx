"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { FileDown, FileJson, KeyRound, Trash2 } from "lucide-react";
import { api, apiUrl, jsonBody } from "@/lib/api";
import { SEVERITIES, styleFor } from "@/lib/severity";
import { SeverityBadge } from "@/features/scans/finding-detail";
import { getReviewKey, setReviewKey } from "./review-key";

type CaseFinding = { id: string; condition: string; level: string; severity: string };
type Decision = {
  id: string;
  decision: "accept" | "edit" | "reject" | "pending";
  corrected_severity: string | null;
  note: string;
};
type Revision = {
  revision: number;
  reviewer: string;
  created: string;
  payload: {
    decisions: Decision[];
    impression: string;
    symptoms: string;
    next_review_step?: string;
    finalize: boolean;
  };
};
type CaseItem = {
  id: string;
  created: string;
  label?: string;
  comparison_group: string;
  comparison_key?: (string | null)[];
  finalized?: boolean;
  findings: CaseFinding[];
  revisions?: Revision[];
};

async function download(path: string, key: string, name: string) {
  const response = await fetch(apiUrl(path), { headers: { "X-Review-Key": key } });
  if (!response.ok) throw new Error(`Export failed (${response.status}).`);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function CaseLibrary() {
  const [key, setKey] = useState("");
  const [draftKey, setDraftKey] = useState("");
  const [cases, setCases] = useState<CaseItem[] | null>(null);
  const [active, setActive] = useState<CaseItem | null>(null);
  const [error, setError] = useState("");
  const headers = useMemo(() => ({ "X-Review-Key": key }), [key]);

  const load = useCallback(async () => {
    if (!key) return;
    try {
      setCases(await api<CaseItem[]>("/api/cases", { headers }));
      setError("");
    } catch (err) {
      setError((err as Error).message);
      setCases(null);
    }
  }, [headers, key]);

  useEffect(() => {
    const saved = getReviewKey();
    setKey(saved);
    setDraftKey(saved);
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function openCase(id: string) {
    try {
      setActive(await api<CaseItem>(`/api/cases/${id}`, { headers }));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (!key || (!cases && error)) {
    return (
      <form
        className="panel mx-auto mt-6 max-w-md space-y-4 p-6"
        onSubmit={(e) => {
          e.preventDefault();
          setReviewKey(draftKey);
          setKey(draftKey);
        }}
      >
        <KeyRound className="text-cobalt" />
        <h2 className="text-xl font-bold">Unlock the case library</h2>
        <p className="text-sm text-graphite">
          Enter REVIEW_ACCESS_TOKEN from backend/.env. It stays in this browser tab only.
        </p>
        <input
          type="password"
          className="field"
          value={draftKey}
          onChange={(e) => setDraftKey(e.target.value)}
          aria-label="Review access key"
          autoComplete="off"
        />
        {error && <p className="text-sm text-sev-severe-ink">{error}</p>}
        <button className="btn btn-primary" disabled={!draftKey}>
          Open cases
        </button>
      </form>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
      <aside className="panel h-fit p-3">
        <h2 className="px-2 pb-2 font-semibold">Saved analyses</h2>
        {cases?.length === 0 && (
          <p className="px-2 pb-3 text-sm text-graphite">
            Nothing saved yet. Use &ldquo;Save to cases&rdquo; on a scan result.
          </p>
        )}
        <ul className="space-y-1">
          {cases?.map((item) => {
            const worst = [...item.findings].sort(
              (a, b) =>
                SEVERITIES.indexOf(b.severity as never) - SEVERITIES.indexOf(a.severity as never),
            )[0];
            return (
              <li key={item.id}>
                <button
                  onClick={() => openCase(item.id)}
                  className={clsx(
                    "w-full rounded-lg p-3 text-left",
                    active?.id === item.id ? "bg-cobalt-wash" : "hover:bg-bone",
                  )}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate font-semibold">
                      {item.label || `Case ${item.id.slice(0, 6)}`}
                    </span>
                    {item.finalized && (
                      <span className="text-xs font-semibold text-sev-normal-ink">Signed off</span>
                    )}
                  </span>
                  <span className="mt-1 flex items-center gap-2 text-sm text-graphite">
                    {item.findings[0]?.condition} · {new Date(item.created).toLocaleDateString()}
                    {worst && (
                      <span
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ background: styleFor(worst.severity).fill }}
                      />
                    )}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </aside>
      {active ? (
        <CaseReview
          key={active.id}
          item={active}
          all={cases ?? []}
          reviewKey={key}
          onChanged={async () => {
            await openCase(active.id);
            await load();
          }}
          onDeleted={async () => {
            setActive(null);
            await load();
          }}
        />
      ) : (
        <div className="panel flex min-h-60 items-center justify-center p-6 text-graphite">
          Select a saved analysis to review it.
        </div>
      )}
      <ValidationStatus headers={headers} />
    </div>
  );
}

function CaseReview({
  item,
  all,
  reviewKey,
  onChanged,
  onDeleted,
}: {
  item: CaseItem;
  all: CaseItem[];
  reviewKey: string;
  onChanged: () => Promise<void>;
  onDeleted: () => Promise<void>;
}) {
  const latest = item.revisions?.at(-1);
  const [decisions, setDecisions] = useState<Decision[]>(
    () =>
      latest?.payload.decisions ??
      item.findings.map((f) => ({
        id: f.id,
        decision: "pending",
        corrected_severity: null,
        note: "",
      })),
  );
  const [impression, setImpression] = useState(latest?.payload.impression ?? "");
  const [symptoms, setSymptoms] = useState(latest?.payload.symptoms ?? "");
  const [nextStep, setNextStep] = useState(latest?.payload.next_review_step ?? "");
  const [message, setMessage] = useState("");
  const headers = { "X-Review-Key": reviewKey };
  const prior = all.find(
    (other) =>
      other.id !== item.id &&
      item.comparison_group &&
      other.comparison_group === item.comparison_group &&
      JSON.stringify(other.comparison_key) === JSON.stringify(item.comparison_key) &&
      other.created < item.created,
  );

  const update = (id: string, change: Partial<Decision>) =>
    setDecisions((current) => current.map((d) => (d.id === id ? { ...d, ...change } : d)));

  async function save(finalize: boolean) {
    setMessage("");
    try {
      const response = await api<{ revision: number }>(
        `/api/cases/${item.id}/reviews`,
        jsonBody(
          {
            expected_revision: latest?.revision ?? 0,
            decisions,
            impression,
            symptoms,
            next_review_step: nextStep,
            finalize,
          },
          headers,
        ),
      );
      setMessage(
        finalize
          ? `Signed off as revision ${response.revision}.`
          : `Saved revision ${response.revision}.`,
      );
      await onChanged();
    } catch (err) {
      setMessage((err as Error).message);
    }
  }

  return (
    <section className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold">{item.label || `Case ${item.id.slice(0, 6)}`}</h2>
          <p className="text-graphite">
            {item.comparison_group ? `Group ${item.comparison_group}, ` : ""}
            {latest ? `revision ${latest.revision} by ${latest.reviewer}` : "not reviewed yet"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            className="btn btn-quiet"
            onClick={() =>
              download(
                `/api/cases/${item.id}/report.pdf`,
                reviewKey,
                `review-${item.id}.pdf`,
              ).catch((e) => setMessage(e.message))
            }
          >
            <FileDown size={16} /> PDF
          </button>
          <button
            className="btn btn-quiet"
            onClick={() =>
              download(`/api/cases/${item.id}/fhir`, reviewKey, `review-${item.id}.json`).catch(
                (e) => setMessage(e.message),
              )
            }
          >
            <FileJson size={16} /> FHIR JSON
          </button>
          <button
            className="btn btn-quiet text-sev-severe-ink"
            onClick={async () => {
              if (!window.confirm("Delete this case and all its reviews?")) return;
              await api(`/api/cases/${item.id}`, { method: "DELETE", headers });
              await onDeleted();
            }}
          >
            <Trash2 size={16} /> Delete
          </button>
        </div>
      </header>

      <div className="panel divide-y divide-rule">
        {item.findings.map((finding) => {
          const decision = decisions.find((d) => d.id === finding.id)!;
          const before = prior?.findings.find((f) => f.level === finding.level);
          return (
            <div key={finding.id} className="grid gap-3 p-4 md:grid-cols-[180px_1fr]">
              <div>
                <p className="font-semibold">
                  {finding.id} {finding.level}
                </p>
                <SeverityBadge severity={finding.severity} />
                {before && <p className="mt-1 text-xs text-graphite">Prior: {before.severity}</p>}
              </div>
              <div className="space-y-2">
                <div
                  className="flex flex-wrap gap-1.5"
                  role="radiogroup"
                  aria-label={`Decision for ${finding.level}`}
                >
                  {(["accept", "edit", "reject", "pending"] as const).map((value) => (
                    <button
                      key={value}
                      role="radio"
                      aria-checked={decision.decision === value}
                      onClick={() => update(finding.id, { decision: value })}
                      className={clsx(
                        "rounded-lg border px-3 py-1.5 text-sm font-semibold",
                        decision.decision === value
                          ? "border-cobalt bg-cobalt-wash text-cobalt-deep"
                          : "border-rule text-graphite hover:border-cobalt",
                      )}
                    >
                      {
                        {
                          accept: "Agree",
                          edit: "Correct",
                          reject: "Reject",
                          pending: "Undecided",
                        }[value]
                      }
                    </button>
                  ))}
                </div>
                {decision.decision === "edit" && (
                  <select
                    className="field max-w-xs"
                    value={decision.corrected_severity ?? ""}
                    onChange={(e) =>
                      update(finding.id, { corrected_severity: e.target.value || null })
                    }
                    aria-label="Corrected grade"
                  >
                    <option value="">Choose the correct grade</option>
                    {SEVERITIES.map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                )}
                <input
                  className="field"
                  placeholder={
                    decision.decision === "edit"
                      ? "Why the grade changes (required)"
                      : "Note (optional)"
                  }
                  value={decision.note}
                  maxLength={1000}
                  onChange={(e) => update(finding.id, { note: e.target.value })}
                />
              </div>
            </div>
          );
        })}
      </div>

      <div className="panel grid gap-4 p-5 md:grid-cols-2">
        <label className="text-sm font-semibold">
          Symptoms and history
          <textarea
            className="field mt-1 min-h-24"
            value={symptoms}
            maxLength={2000}
            onChange={(e) => setSymptoms(e.target.value)}
          />
        </label>
        <label className="text-sm font-semibold">
          Impression
          <textarea
            className="field mt-1 min-h-24"
            value={impression}
            maxLength={4000}
            onChange={(e) => setImpression(e.target.value)}
          />
        </label>
        <label className="text-sm font-semibold md:col-span-2">
          Next review step
          <input
            className="field mt-1"
            value={nextStep}
            maxLength={2000}
            onChange={(e) => setNextStep(e.target.value)}
          />
        </label>
        <div className="flex flex-wrap items-center gap-2 md:col-span-2">
          <button className="btn btn-quiet" onClick={() => save(false)}>
            Save draft
          </button>
          <button className="btn btn-primary" onClick={() => save(true)}>
            Sign off
          </button>
          {message && (
            <p role="status" className="text-sm text-graphite">
              {message}
            </p>
          )}
        </div>
        <p className="text-xs text-graphite md:col-span-2">
          Each save is a new revision; earlier revisions are kept. Changes after sign-off are
          exported as amended.
        </p>
      </div>
      {(item.revisions?.length ?? 0) > 0 && (
        <details className="panel p-5">
          <summary className="cursor-pointer font-semibold">Revision history</summary>
          <ol className="mt-3 space-y-1 text-sm">
            {item.revisions!.map((r) => (
              <li key={r.revision}>
                Revision {r.revision}, {new Date(r.created).toLocaleString()}, {r.reviewer}
                {r.payload.finalize ? ", signed off" : ""}
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}

function ValidationStatus({ headers }: { headers: Record<string, string> }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    api<Record<string, unknown>>("/api/cases/validation", { headers })
      .then(setData)
      .catch(() => setData(null));
  }, [headers]);
  if (!data) return null;
  const pending = data.status === "pending";
  return (
    <section className="panel p-5 lg:col-span-2">
      <h2 className="font-semibold">Model validation</h2>
      {pending ? (
        <p className="mt-1 text-sm text-graphite">
          No held-out evaluation has been run yet, so no accuracy figure is shown. Run
          tools/evaluate.py on labelled predictions to populate this section.
        </p>
      ) : (
        <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-bone p-3 text-xs">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </section>
  );
}
