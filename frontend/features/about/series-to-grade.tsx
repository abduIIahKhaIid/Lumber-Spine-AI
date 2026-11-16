"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";
import { Pause, Play } from "lucide-react";
import { styleFor } from "@/lib/severity";

export type Stage = { title: string; text: string };

const STEP_MS = 2800;

// A schematic sagittal lumbar spine (not patient data): five discs from L1/L2 to L5/S1.
const LEVELS = [
  { label: "L1/L2", x: 200, y: 112, severity: "Normal/Mild" },
  { label: "L2/L3", x: 207, y: 160, severity: "Normal/Mild" },
  { label: "L3/L4", x: 209, y: 208, severity: "Moderate" },
  { label: "L4/L5", x: 207, y: 256, severity: "Severe" },
  { label: "L5/S1", x: 200, y: 303, severity: "Moderate" },
] as const;
// Stage 1 is coarse: its points sit a little off the disc centres until Stage 2 refines them.
const COARSE = [
  [9, -7],
  [-8, 6],
  [10, 5],
  [-7, -8],
  [8, 7],
];
const BODIES = [88, 136, 184, 232, 280, 326];
const SHEETS = [5, 4, 3, 2, 1];

/** Looping animation of the full-series pipeline, with the step list it follows. */
export default function SeriesToGrade({ stages }: { stages: Stage[] }) {
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(true);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setPlaying(false);
      setStep(stages.length - 1);
    }
  }, [stages.length]);

  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => setStep((s) => (s + 1) % stages.length), STEP_MS);
    return () => clearInterval(timer);
  }, [playing, stages.length]);

  const located = step >= 1;
  const refined = step >= 2;
  const graded = step >= 3;

  return (
    <div className="mt-5">
      <figure className="film relative overflow-hidden p-0">
        <svg
          viewBox="0 0 640 400"
          role="img"
          aria-label={`Animation, step ${step + 1} of ${stages.length}: ${stages[step].title}`}
          className="block h-auto w-full"
        >
          <defs>
            <linearGradient id="sweep" x1="0" x2="1">
              <stop offset="0" stopColor="#2b59c3" stopOpacity="0" />
              <stop offset="0.5" stopColor="#6d8fe0" stopOpacity="0.55" />
              <stop offset="1" stopColor="#2b59c3" stopOpacity="0" />
            </linearGradient>
          </defs>

          {/* The series: a stack of slices that fans out while it is read */}
          {SHEETS.map((depth) => (
            <rect
              key={depth}
              x={80}
              y={60}
              width={300}
              height={300}
              rx={10}
              fill="#18232f"
              stroke="#2c3a48"
              style={{
                transform: `translate(${step === 0 ? -14 * depth : -7 * depth}px, ${
                  step === 0 ? -9 * depth : -5 * depth
                }px)`,
                opacity: graded ? 0.25 : 0.9 - depth * 0.12,
                transition: "transform 900ms ease, opacity 900ms ease",
              }}
            />
          ))}
          <rect x={80} y={60} width={300} height={300} rx={10} fill="#0e1620" stroke="#3a4a5a" />

          {/* Sagittal anatomy on the front slice */}
          <path
            d="M262 70 C 276 160, 280 250, 264 352"
            stroke="#3d4b59"
            strokeWidth={26}
            fill="none"
            strokeLinecap="round"
          />
          {BODIES.map((y, i) => {
            const x = 196 + Math.sin((i / 5) * Math.PI) * 14;
            return (
              <rect
                key={y}
                x={x - 36}
                y={y - 19}
                width={72}
                height={38}
                rx={9}
                fill={i === 5 ? "#9aa5b1" : "#b9c3cd"}
                transform={`rotate(${-6 + i * 3} ${x} ${y})`}
              />
            );
          })}
          {LEVELS.map((level) => (
            <ellipse key={level.label} cx={level.x} cy={level.y} rx={30} ry={6} fill="#5d6b78" />
          ))}

          {/* Stage 1: a plane sweeps through the volume */}
          <rect
            x={80}
            y={60}
            width={60}
            height={300}
            fill="url(#sweep)"
            style={{
              opacity: step === 1 ? 1 : 0,
              transform: step === 1 ? "translateX(240px)" : "translateX(0px)",
              transition:
                step === 1
                  ? "transform 2200ms ease-in-out, opacity 300ms ease"
                  : "opacity 300ms ease",
            }}
          />

          {/* Level points: coarse in stage 1, refined in stage 2 */}
          {LEVELS.map((level, i) => {
            const [dx, dy] = refined ? [0, 0] : COARSE[i];
            const color = graded ? styleFor(level.severity).fill : "#7aa2ff";
            return (
              <g
                key={level.label}
                style={{
                  opacity: located ? 1 : 0,
                  transform: `translate(${dx}px, ${dy}px)`,
                  transition: `opacity 400ms ease ${i * 120}ms, transform 900ms cubic-bezier(.2,.8,.2,1)`,
                }}
              >
                <rect
                  x={level.x - 34}
                  y={level.y - 15}
                  width={68}
                  height={30}
                  rx={4}
                  fill="none"
                  stroke={color}
                  strokeWidth={3}
                  style={{ opacity: graded ? 1 : 0, transition: "opacity 500ms ease" }}
                />
                <circle cx={level.x} cy={level.y} r={graded ? 0 : 5} fill={color} />
                {step === 2 && (
                  <circle
                    cx={level.x}
                    cy={level.y}
                    r={14}
                    fill="none"
                    stroke="#7aa2ff"
                    strokeWidth={2}
                    className="animate-ping"
                    style={{ transformOrigin: `${level.x}px ${level.y}px` }}
                  />
                )}
                <text
                  x={level.x - 52}
                  y={level.y + 5}
                  textAnchor="end"
                  fontSize={13}
                  fontWeight={700}
                  fill={graded ? color : "#c8d3df"}
                  style={{ transition: "fill 500ms ease" }}
                >
                  {level.label}
                </text>
              </g>
            );
          })}

          {/* Stage 3: the grade of each level */}
          <g style={{ opacity: graded ? 1 : 0, transition: "opacity 600ms ease 200ms" }}>
            <text x={430} y={92} fontSize={14} fontWeight={700} fill="#ffffff">
              Grade per level
            </text>
            {LEVELS.map((level, i) => {
              const style = styleFor(level.severity);
              return (
                <g key={level.label} transform={`translate(430 ${112 + i * 46})`}>
                  <rect width={170} height={36} rx={8} fill="#18232f" />
                  <rect width={6} height={36} rx={3} fill={style.fill} />
                  <text x={16} y={23} fontSize={13} fontWeight={700} fill="#ffffff">
                    {level.label}
                  </text>
                  <text x={160} y={23} fontSize={13} textAnchor="end" fill={style.fill}>
                    {style.short}
                  </text>
                </g>
              );
            })}
          </g>
          <g style={{ opacity: graded ? 0 : 1, transition: "opacity 400ms ease" }}>
            <text x={430} y={190} fontSize={13} fill="#8a99a8">
              {step === 0 ? "Reading slices" : step === 1 ? "Locating levels" : "Refining points"}
            </text>
            <rect x={430} y={202} width={170} height={6} rx={3} fill="#18232f" />
            <rect
              x={430}
              y={202}
              height={6}
              rx={3}
              fill="#2b59c3"
              style={{ width: ((step + 1) / stages.length) * 170, transition: "width 600ms ease" }}
            />
          </g>
        </svg>
        <button
          type="button"
          onClick={() => setPlaying(!playing)}
          className="absolute bottom-3 right-3 flex items-center gap-1.5 rounded-lg bg-white/10 px-2.5 py-1.5 text-sm text-white hover:bg-white/20"
          aria-label={playing ? "Pause animation" : "Play animation"}
        >
          {playing ? <Pause size={14} /> : <Play size={14} />}
          {playing ? "Pause" : "Play"}
        </button>
      </figure>

      <ol className="mt-6 space-y-3">
        {stages.map((stage, index) => (
          <li key={stage.title}>
            <button
              type="button"
              onClick={() => {
                setStep(index);
                setPlaying(false);
              }}
              aria-current={index === step ? "step" : undefined}
              className={clsx(
                "flex w-full gap-4 rounded-xl p-3 text-left transition-colors",
                index === step ? "bg-paper shadow-sm" : "hover:bg-paper/60",
              )}
            >
              <span
                className={clsx(
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-full font-bold transition-colors",
                  index === step ? "bg-cobalt text-white" : "bg-ink text-white",
                )}
              >
                {index + 1}
              </span>
              <span>
                <span className="block font-semibold">{stage.title}</span>
                <span className="mt-1 block leading-relaxed text-graphite">{stage.text}</span>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
