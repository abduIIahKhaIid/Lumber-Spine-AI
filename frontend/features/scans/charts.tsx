"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { SEVERITIES, severityStyle } from "@/lib/severity";
import type { AnalysisResult, Finding } from "./types";

const axis = { fontSize: 12, fill: "#5b6b7b" };

/** Stacked bars: how each level's score splits across Normal/Mild, Moderate and Severe. */
export function LevelProfileChart({
  findings,
  selectedId,
  onSelect,
}: {
  findings: Finding[];
  selectedId?: string;
  onSelect: (finding: Finding) => void;
}) {
  const data = findings.map((f) => ({
    id: f.id,
    level: f.level_label,
    ...Object.fromEntries(SEVERITIES.map((s) => [s, Math.round((f.class_scores[s] ?? 0) * 100)])),
  }));
  return (
    <figure className="panel p-5">
      <figcaption className="mb-3">
        <h3 className="font-semibold">Score profile by level</h3>
        <p className="text-sm text-graphite">
          Share of the model score per grade. Select a bar to open that level.
        </p>
      </figcaption>
      <div style={{ height: Math.max(180, findings.length * 34 + 40) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            layout="vertical"
            margin={{ left: 4, right: 12, top: 4, bottom: 4 }}
            barCategoryGap={6}
          >
            <CartesianGrid horizontal={false} stroke="#e2e8f0" />
            <XAxis
              type="number"
              domain={[0, 100]}
              ticks={[0, 25, 50, 75, 100]}
              allowDataOverflow
              tick={axis}
              tickFormatter={(v) => `${v}%`}
              stroke="#cbd5e1"
            />
            <YAxis type="category" dataKey="level" width={64} tick={axis} stroke="#cbd5e1" />
            <Tooltip
              cursor={{ fill: "#e4ebf9" }}
              formatter={(value, name) => [`${value}%`, String(name)]}
              contentStyle={{ borderRadius: 10, borderColor: "#d5dce3", fontSize: 13 }}
            />
            {SEVERITIES.map((s, i) => (
              <Bar
                key={s}
                dataKey={s}
                stackId="score"
                fill={severityStyle[s].fill}
                radius={i === SEVERITIES.length - 1 ? [0, 4, 4, 0] : 0}
                onClick={(entry) => {
                  const hit = findings.find((f) => f.id === (entry as { id?: string }).id);
                  if (hit) onSelect(hit);
                }}
              >
                {data.map((row) => (
                  <Cell
                    key={row.id}
                    cursor="pointer"
                    fillOpacity={!selectedId || selectedId === row.id ? 1 : 0.45}
                  />
                ))}
              </Bar>
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ul className="mt-3 flex flex-wrap gap-4 text-xs text-graphite">
        {SEVERITIES.map((s) => (
          <li key={s} className="flex items-center gap-1.5">
            <span
              className="h-2.5 w-2.5 rounded-sm"
              style={{ background: severityStyle[s].fill }}
            />
            {s}
          </li>
        ))}
      </ul>
    </figure>
  );
}

/** Count of levels per grade. */
export function GradeDistribution({ summary }: { summary: AnalysisResult["summary"] }) {
  const data = SEVERITIES.map((s) => ({
    grade: severityStyle[s].short,
    count: summary.counts[s] ?? 0,
    s,
  }));
  return (
    <figure className="panel p-5">
      <figcaption className="mb-3">
        <h3 className="font-semibold">Levels per grade</h3>
        <p className="text-sm text-graphite">
          {summary.total} assessed
          {summary.not_assessed.length ? `, ${summary.not_assessed.length} not assessed` : ""}.
        </p>
      </figcaption>
      <div className="h-[180px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ left: -18, right: 4, top: 8, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="#e2e8f0" />
            <XAxis dataKey="grade" tick={axis} stroke="#cbd5e1" />
            <YAxis allowDecimals={false} tick={axis} stroke="#cbd5e1" />
            <Tooltip
              cursor={{ fill: "#eef1f4" }}
              contentStyle={{ borderRadius: 10, borderColor: "#d5dce3", fontSize: 13 }}
            />
            <Bar dataKey="count" name="Levels" radius={[6, 6, 0, 0]} maxBarSize={56}>
              {data.map((row) => (
                <Cell key={row.s} fill={severityStyle[row.s].fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
