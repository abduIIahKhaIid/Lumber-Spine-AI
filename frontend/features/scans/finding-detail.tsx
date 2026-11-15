"use client";

import { AlertTriangle } from "lucide-react";
import { SEVERITIES, percent, styleFor } from "@/lib/severity";
import type { Finding } from "./types";

export function SeverityBadge({ severity, size = "sm" }: { severity: string; size?: "sm" | "lg" }) {
  const style = styleFor(severity);
  return (
    <span
      className={
        size === "lg"
          ? "inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-bold"
          : "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-bold"
      }
      style={{ background: style.wash, color: style.ink }}
    >
      <span className="h-2 w-2 rounded-full" style={{ background: style.fill }} />
      {severity}
    </span>
  );
}

export default function FindingDetail({ finding }: { finding?: Finding }) {
  if (!finding) {
    return (
      <section className="panel p-5 text-sm text-graphite">
        No level was graded in this image, so there is nothing to inspect. Try another slice or the
        full-series upload.
      </section>
    );
  }
  const explanation = finding.explanation;
  const calibrated = finding.calibration.status === "applied";
  return (
    <section className="panel flex flex-col gap-4 p-5" aria-label="Selected level">
      <header className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm text-graphite">
            {finding.id} · {finding.condition_name}
          </p>
          <h2 className="mt-0.5 text-2xl font-bold tracking-tight">{finding.level_label}</h2>
          {finding.slice_number && (
            <p className="text-sm text-graphite">Slice {finding.slice_number}</p>
          )}
        </div>
        <SeverityBadge severity={finding.severity} size="lg" />
      </header>

      <div className="grid grid-cols-2 gap-3">
        <figure>
          {explanation.crop_image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={`data:image/png;base64,${explanation.crop_image}`}
              alt="Region the severity model graded"
              className="aspect-square w-full rounded-lg bg-film object-cover"
            />
          ) : (
            <div className="aspect-square rounded-lg bg-film" />
          )}
          <figcaption className="mt-1.5 text-xs text-graphite">Model input</figcaption>
        </figure>
        <figure>
          {explanation.heatmap_image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={`data:image/png;base64,${explanation.heatmap_image}`}
              alt={`Focus map tinted ${finding.severity.toLowerCase()}`}
              className="aspect-square w-full rounded-lg bg-film object-cover"
            />
          ) : (
            <div className="flex aspect-square items-center justify-center rounded-lg bg-film p-3 text-center text-xs text-slate-400">
              Focus map unavailable
            </div>
          )}
          <figcaption className="mt-1.5 text-xs text-graphite">
            Focus map, tinted by grade
          </figcaption>
        </figure>
      </div>

      <div>
        <h3 className="mb-2 text-sm font-semibold">Model scores</h3>
        <ul className="space-y-2">
          {SEVERITIES.map((name) => {
            const value = finding.class_scores[name] ?? 0;
            const style = styleFor(name);
            return (
              <li
                key={name}
                className="grid grid-cols-[6.5rem_1fr_3rem] items-center gap-2 text-sm"
              >
                <span className={name === finding.severity ? "font-bold" : "text-graphite"}>
                  {name}
                </span>
                <span className="h-2.5 overflow-hidden rounded-full bg-bone">
                  <span
                    className="block h-full rounded-full"
                    style={{ width: `${value * 100}%`, background: style.fill }}
                  />
                </span>
                <span className="text-right tabular-nums">{percent(value)}</span>
              </li>
            );
          })}
        </ul>
        <p className="mt-2 text-xs text-graphite">
          {calibrated
            ? "Calibrated scores are available for this checkpoint."
            : "Raw scores, not calibrated probabilities."}
          {finding.localization_confidence !== null &&
            ` Level detection confidence ${percent(finding.localization_confidence)}.`}
        </p>
      </div>

      {finding.uncertainty.status === "review" && (
        <div className="rounded-lg border border-sev-moderate/50 bg-sev-moderate/10 p-3 text-sm">
          <p className="flex items-center gap-2 font-semibold text-sev-moderate-ink">
            <AlertTriangle size={16} /> Check this level on the original slices
          </p>
          <ul className="mt-1.5 list-disc pl-5 text-ink/80">
            {finding.uncertainty.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-xs text-graphite">
        {explanation.method}. Highlighted pixels influenced the score; they do not prove a lesion.
      </p>
    </section>
  );
}
