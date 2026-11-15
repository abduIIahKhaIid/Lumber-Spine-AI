"use client";

import { useState } from "react";
import SpineLadder from "@/features/scans/spine-ladder";
import { SeverityBadge } from "@/features/scans/finding-detail";
import type { Finding } from "@/features/scans/types";

const demo: [string, Finding["severity"], number][] = [
  ["L1/L2", "Normal/Mild", 0.91],
  ["L2/L3", "Normal/Mild", 0.84],
  ["L3/L4", "Moderate", 0.62],
  ["L4/L5", "Severe", 0.77],
  ["L5/S1", "Moderate", 0.58],
];

const findings = demo.map(
  ([level, severity, score], i) =>
    ({
      id: `F${i + 1}`,
      level,
      side: null,
      level_label: level,
      severity,
      severity_confidence: score,
      uncertainty: { status: score < 0.6 ? "review" : "no_flag", reasons: [], method: "" },
    }) as unknown as Finding,
);

/** Example output on the home page: the same level ladder the results view uses. */
export default function DemoLadder() {
  const [selected, setSelected] = useState("F4");
  const finding = findings.find((f) => f.id === selected)!;
  return (
    <div className="film grid gap-6 p-6 sm:grid-cols-[minmax(0,240px)_1fr] sm:items-center">
      <div className="rounded-xl bg-bone p-3">
        <SpineLadder
          findings={findings}
          sided={false}
          selectedId={selected}
          onSelect={(f) => setSelected(f.id)}
        />
      </div>
      <div>
        <p className="text-sm text-slate-400">Example result, spinal canal stenosis</p>
        <p className="mt-2 text-4xl font-bold tracking-tight text-white">{finding.level_label}</p>
        <div className="mt-3">
          <SeverityBadge severity={finding.severity} size="lg" />
        </div>
        <p className="mt-4 max-w-xs text-sm leading-relaxed text-slate-300">
          Top score {Math.round(finding.severity_confidence * 100)}%.
          {finding.uncertainty.status === "review"
            ? " Scores are close, so this level is marked for a second look."
            : " Select another level on the column to compare."}
        </p>
      </div>
    </div>
  );
}
