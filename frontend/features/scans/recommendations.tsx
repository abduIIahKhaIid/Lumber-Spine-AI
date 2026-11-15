"use client";

import { useState } from "react";
import clsx from "clsx";
import type { Finding, Recommendation } from "./types";

const PRIORITY = {
  high: { label: "Act first", color: "#b91c1c", bar: "#ef4444" },
  medium: { label: "Review", color: "#a16207", bar: "#eab308" },
  low: { label: "Keep in mind", color: "#1f4396", bar: "#2b59c3" },
} as const;

export default function Recommendations({
  items,
  findings,
  onSelect,
}: {
  items: Recommendation[];
  findings: Finding[];
  onSelect: (finding: Finding) => void;
}) {
  const [audience, setAudience] = useState<"clinician" | "patient">("clinician");
  return (
    <section className="panel p-5" aria-labelledby="next-steps">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="next-steps" className="text-lg font-bold">
            Suggested next steps
          </h2>
          <p className="text-sm text-graphite">
            Generated from the grades and quality checks above. Review prompts, not treatment
            advice.
          </p>
        </div>
        <div className="flex rounded-lg border border-rule bg-bone p-0.5" role="radiogroup">
          {(["clinician", "patient"] as const).map((value) => (
            <button
              key={value}
              role="radio"
              aria-checked={audience === value}
              onClick={() => setAudience(value)}
              className={clsx(
                "rounded-md px-3 py-1.5 text-sm font-semibold",
                audience === value ? "bg-paper text-ink shadow-sm" : "text-graphite",
              )}
            >
              {value === "clinician" ? "For clinicians" : "Plain language"}
            </button>
          ))}
        </div>
      </header>
      <ol className="mt-4 space-y-3">
        {items.map((item) => {
          const style = PRIORITY[item.priority];
          return (
            <li
              key={item.id}
              className="relative overflow-hidden rounded-xl border border-rule bg-paper py-3 pl-5 pr-4"
            >
              <span className="absolute inset-y-0 left-0 w-1.5" style={{ background: style.bar }} />
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-xs font-bold" style={{ color: style.color }}>
                  {style.label}
                </span>
                <h3 className="font-semibold">{item.title}</h3>
              </div>
              <p className="mt-1 text-sm leading-relaxed text-ink/85">
                {audience === "clinician" ? item.clinician : item.patient}
              </p>
              {item.evidence.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {item.evidence.map((id) => {
                    const finding = findings.find((f) => f.id === id);
                    return finding ? (
                      <button
                        key={id}
                        onClick={() => onSelect(finding)}
                        className="rounded-md bg-bone px-2 py-0.5 text-xs font-semibold text-cobalt-deep hover:bg-cobalt-wash"
                      >
                        {id} {finding.level_label}
                      </button>
                    ) : null;
                  })}
                </div>
              )}
            </li>
          );
        })}
      </ol>
      {items[0]?.rules_version && (
        <p className="mt-3 text-xs text-graphite">
          Rule set {items[0].rules_version}, pending clinician approval.
        </p>
      )}
    </section>
  );
}
