"use client";

import clsx from "clsx";
import { styleFor } from "@/lib/severity";
import type { Finding } from "./types";

const LEVELS = ["L1/L2", "L2/L3", "L3/L4", "L4/L5", "L5/S1"] as const;
const VERTEBRAE = ["L1", "L2", "L3", "L4", "L5"];

/**
 * Lumbar column drawn as vertebral bodies with the five disc levels between them.
 * Each disc level is a button colored by the graded severity; sided conditions
 * (foraminal / subarticular) split the disc into left and right halves.
 */
export default function SpineLadder({
  findings,
  sided,
  selectedId,
  onSelect,
}: {
  findings: Finding[];
  sided: boolean;
  selectedId?: string;
  onSelect: (finding: Finding) => void;
}) {
  const find = (level: string, side: "left" | "right" | null) =>
    findings.find((f) => f.level === level && (sided ? f.side === side : true));

  const BODY_H = 50;
  const DISC_H = 26;
  const STEP = BODY_H + DISC_H;
  const width = 248;
  const top = sided ? 24 : 8;
  const x0 = 64;
  const bodyW = 120;

  const disc = (level: string, index: number) => {
    const y = top + index * STEP + BODY_H;
    const sides: ("left" | "right" | null)[] = sided ? ["right", "left"] : [null];
    // Radiological convention: the patient's right is on the viewer's left.
    return (
      <g key={level}>
        <text
          x={x0 - 12}
          y={y + DISC_H / 2 + 4}
          textAnchor="end"
          className="fill-graphite text-[12px] font-semibold"
        >
          {level}
        </text>
        {sides.map((side, i) => {
          const finding = find(level, side);
          const style = styleFor(finding?.severity);
          const w = sided ? bodyW / 2 - 2 : bodyW;
          const x = sided ? x0 + i * (bodyW / 2 + 2) : x0;
          const selected = finding && finding.id === selectedId;
          const label = `${side ? `${side} ` : ""}${level}: ${finding ? finding.severity : "not assessed"}`;
          return (
            <g key={side ?? "c"}>
              <rect
                role="button"
                tabIndex={finding ? 0 : -1}
                aria-label={label}
                aria-pressed={selected}
                x={x}
                y={y + 3}
                width={w}
                height={DISC_H - 6}
                rx={9}
                fill={finding ? style.fill : "url(#unassessed)"}
                stroke={selected ? "#14212e" : "transparent"}
                strokeWidth={3}
                className={clsx(finding && "cursor-pointer")}
                onClick={() => finding && onSelect(finding)}
                onKeyDown={(event) => {
                  if (finding && (event.key === "Enter" || event.key === " ")) {
                    event.preventDefault();
                    onSelect(finding);
                  }
                }}
              >
                <title>{label}</title>
              </rect>
              {finding?.uncertainty.status === "review" && (
                <circle cx={x + w - 9} cy={y + DISC_H / 2} r={4} fill="#14212e" />
              )}
            </g>
          );
        })}
      </g>
    );
  };

  const height = top + LEVELS.length * STEP + 64;
  return (
    <figure className="select-none">
      <svg viewBox={`0 0 ${width} ${height}`} className="mx-auto w-full max-w-[248px]">
        <defs>
          <pattern
            id="unassessed"
            width="6"
            height="6"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <rect width="6" height="6" fill="#e2e8f0" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="#cbd5e1" strokeWidth="3" />
          </pattern>
        </defs>
        {sided && (
          <>
            <text
              x={x0 + bodyW / 4}
              y={14}
              textAnchor="middle"
              className="fill-graphite text-[11px]"
            >
              Right
            </text>
            <text
              x={x0 + (3 * bodyW) / 4}
              y={14}
              textAnchor="middle"
              className="fill-graphite text-[11px]"
            >
              Left
            </text>
          </>
        )}
        {VERTEBRAE.map((name, index) => (
          <g key={name}>
            <rect
              x={x0}
              y={top + index * STEP}
              width={bodyW}
              height={BODY_H}
              rx={12}
              fill="#ffffff"
              stroke="#c3ccd6"
              strokeWidth={1.5}
            />
            <text
              x={x0 + bodyW / 2}
              y={top + index * STEP + BODY_H / 2 + 5}
              textAnchor="middle"
              className="fill-ink text-[14px] font-bold"
            >
              {name}
            </text>
          </g>
        ))}
        <path
          d={`M${x0} ${top + 5 * STEP} h${bodyW} l-18 46 q-42 14 -84 0 z`}
          fill="#ffffff"
          stroke="#c3ccd6"
          strokeWidth={1.5}
        />
        <text
          x={x0 + bodyW / 2}
          y={top + 5 * STEP + 28}
          textAnchor="middle"
          className="fill-ink text-[14px] font-bold"
        >
          S1
        </text>
        {LEVELS.map((level, index) => disc(level, index))}
      </svg>
      <figcaption className="sr-only">
        Lumbar levels colored by graded severity. Select a level to inspect it.
      </figcaption>
    </figure>
  );
}
