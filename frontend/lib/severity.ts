/** Severity vocabulary and colors. Mirrors backend/app/ml/severity.py. */
export const SEVERITIES = ["Normal/Mild", "Moderate", "Severe"] as const;
export type Severity = (typeof SEVERITIES)[number];

export const severityStyle: Record<
  Severity,
  { fill: string; ink: string; wash: string; short: string }
> = {
  "Normal/Mild": { fill: "#22c55e", ink: "#15803d", wash: "#dcfce7", short: "Normal" },
  Moderate: { fill: "#eab308", ink: "#a16207", wash: "#fef9c3", short: "Moderate" },
  Severe: { fill: "#ef4444", ink: "#b91c1c", wash: "#fee2e2", short: "Severe" },
};

const fallback = { fill: "#94a3b8", ink: "#475569", wash: "#f1f5f9", short: "Unknown" };

export function styleFor(severity: string | null | undefined) {
  return severityStyle[severity as Severity] ?? fallback;
}

export function rank(severity: string | null | undefined): number {
  return SEVERITIES.indexOf(severity as Severity);
}

export function percent(value: number | null | undefined): string {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "–";
}
