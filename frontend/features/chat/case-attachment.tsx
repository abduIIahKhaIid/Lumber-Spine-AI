"use client";

import { FileHeart } from "lucide-react";
import { SEVERITIES, styleFor } from "@/lib/severity";

export type CaseContext = {
  condition?: string;
  plane?: string;
  sequence?: string;
  mode?: string;
  preview?: string;
  findings?: { id: string; level: string; severity: string }[];
};

/** The scan result attached to a conversation, shown in the chat like a file attachment. */
export default function CaseAttachment({ context }: { context: CaseContext }) {
  const findings = context.findings ?? [];
  const counts = SEVERITIES.map(
    (s) => [s, findings.filter((f) => f.severity === s).length] as const,
  );
  return (
    <div className="ml-auto w-full max-w-[85%]">
      <p className="mb-1.5 flex items-center justify-end gap-1.5 text-xs font-semibold text-graphite">
        <FileHeart size={14} /> Attached scan result
      </p>
      <figure className="overflow-hidden rounded-2xl rounded-br-md border border-rule bg-paper">
        <div className="flex flex-col sm:flex-row">
          {context.preview && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={`data:image/jpeg;base64,${context.preview}`}
              alt="Annotated slice from the attached result"
              className="h-44 w-full bg-film object-contain sm:w-44"
            />
          )}
          <figcaption className="min-w-0 flex-1 p-4">
            <p className="font-semibold">{context.condition ?? "Scan result"}</p>
            <p className="text-sm text-graphite">
              {[context.plane, context.sequence].filter(Boolean).join(" ")}
              {context.mode ? `, ${context.mode === "multi" ? "full series" : "single slice"}` : ""}
            </p>
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-graphite">
              {counts.map(([name, count]) => (
                <span key={name} className="flex items-center gap-1">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ background: styleFor(name).fill }}
                  />
                  {count} {styleFor(name).short.toLowerCase()}
                </span>
              ))}
            </div>
            <ul className="mt-3 flex flex-wrap gap-1.5">
              {findings.map((f) => {
                const style = styleFor(f.severity);
                return (
                  <li
                    key={f.id}
                    className="rounded-md px-2 py-0.5 text-xs font-semibold"
                    style={{ background: style.wash, color: style.ink }}
                    title={`${f.id}: ${f.severity}`}
                  >
                    {f.id} {f.level}
                  </li>
                );
              })}
            </ul>
          </figcaption>
        </div>
      </figure>
    </div>
  );
}
