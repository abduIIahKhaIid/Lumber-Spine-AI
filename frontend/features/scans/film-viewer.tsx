"use client";

import { useState } from "react";
import clsx from "clsx";
import { Eye, EyeOff, Maximize2, Minimize2, Tag } from "lucide-react";
import { styleFor } from "@/lib/severity";
import { nearestOnRect, placeLabels } from "./labels";
import type { Finding, ScanImage } from "./types";

/** Dark viewing panel: MRI slice with severity-colored level boxes drawn as an SVG overlay. */
export default function FilmViewer({
  images,
  findings,
  imageIndex,
  onImageChange,
  selectedId,
  onSelect,
}: {
  images: ScanImage[];
  findings: Finding[];
  imageIndex: number;
  onImageChange: (index: number) => void;
  selectedId?: string;
  onSelect: (finding: Finding) => void;
}) {
  const [showBoxes, setShowBoxes] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [large, setLarge] = useState(false);
  const image = images[imageIndex] ?? images[0];
  if (!image) return null;
  const onImage = findings.filter((f) => f.image_index === image.index);
  const stroke = Math.max(2.5, image.width / 180);
  const font = Math.max(12, image.width / 34);
  const pad = font * 0.4;
  const labels = placeLabels(
    onImage.map((f) => ({
      box: f.box,
      side: f.side,
      width: f.level_label.length * font * 0.62 + pad * 2,
      height: font * 1.45,
    })),
    image.width,
    image.height,
    pad,
  );

  return (
    <section className="film flex flex-col overflow-hidden" aria-label="Image viewer">
      <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-3 py-2.5">
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Slices">
          {images.map((item, i) => (
            <button
              key={item.index}
              role="tab"
              aria-selected={i === imageIndex}
              onClick={() => onImageChange(i)}
              className={clsx(
                "rounded-md px-2.5 py-1 text-xs font-semibold",
                i === imageIndex ? "bg-white text-film" : "text-slate-300 hover:bg-white/10",
              )}
            >
              {item.slice_number ? `Slice ${item.slice_number}` : "Image"}
            </button>
          ))}
        </div>
        <div className="ml-auto flex gap-1">
          <ToolButton
            label={showBoxes ? "Hide boxes" : "Show boxes"}
            onClick={() => setShowBoxes(!showBoxes)}
          >
            {showBoxes ? <Eye size={16} /> : <EyeOff size={16} />}
          </ToolButton>
          <ToolButton
            label={showLabels ? "Hide labels" : "Show labels"}
            onClick={() => setShowLabels(!showLabels)}
            active={showLabels}
          >
            <Tag size={16} />
          </ToolButton>
          <ToolButton label={large ? "Fit to panel" : "Enlarge"} onClick={() => setLarge(!large)}>
            {large ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </ToolButton>
        </div>
      </div>
      <div
        className={clsx(
          "relative flex items-center justify-center overflow-auto bg-black p-2",
          large ? "max-h-[85vh]" : "max-h-[68vh]",
        )}
      >
        <div className={clsx("relative", large ? "w-[min(1100px,200%)]" : "w-full max-w-[640px]")}>
          {/* eslint-disable-next-line @next/next/no-img-element -- data URL from the API */}
          <img
            src={`data:image/png;base64,${image.original}`}
            alt={`MRI ${image.slice_number ? `slice ${image.slice_number}` : "image"}`}
            className="block h-auto w-full"
          />
          {showBoxes && (
            <svg
              viewBox={`0 0 ${image.width} ${image.height}`}
              className="absolute inset-0 h-full w-full"
            >
              {onImage.map((f) => {
                const [x0, y0, x1, y1] = f.box;
                const style = styleFor(f.severity);
                const selected = f.id === selectedId;
                return (
                  <g key={f.id} opacity={selectedId && !selected ? 0.55 : 1}>
                    <rect
                      x={x0}
                      y={y0}
                      width={x1 - x0}
                      height={y1 - y0}
                      rx={stroke * 1.5}
                      fill={style.fill}
                      fillOpacity={selected ? 0.22 : 0.12}
                      stroke={style.fill}
                      strokeWidth={selected ? stroke * 1.7 : stroke}
                      className="cursor-pointer"
                      onClick={() => onSelect(f)}
                    >
                      <title>{`${f.level_label}: ${f.severity}`}</title>
                    </rect>
                  </g>
                );
              })}
              {showLabels &&
                onImage.map((f, i) => {
                  const rect = labels[i];
                  const style = styleFor(f.severity);
                  const selected = f.id === selectedId;
                  const [bx, by] = nearestOnRect(
                    f.box,
                    (rect[0] + rect[2]) / 2,
                    (rect[1] + rect[3]) / 2,
                  );
                  const [ex, ey] = nearestOnRect(rect, bx, by);
                  const detached = Math.abs(ex - bx) + Math.abs(ey - by) > pad * 2;
                  return (
                    <g
                      key={`label-${f.id}`}
                      opacity={selectedId && !selected ? 0.55 : 1}
                      className="cursor-pointer"
                      onClick={() => onSelect(f)}
                    >
                      {detached && (
                        <line
                          x1={ex}
                          y1={ey}
                          x2={bx}
                          y2={by}
                          stroke={style.fill}
                          strokeWidth={stroke * 0.8}
                        />
                      )}
                      <rect
                        x={rect[0]}
                        y={rect[1]}
                        width={rect[2] - rect[0]}
                        height={rect[3] - rect[1]}
                        rx={font * 0.3}
                        fill={style.fill}
                        stroke={selected ? "#ffffff" : "none"}
                        strokeWidth={stroke * 0.6}
                      />
                      <text
                        x={rect[0] + pad}
                        y={rect[1] + font * 1.05}
                        fontSize={font}
                        fontWeight={700}
                        fill="#0e1620"
                      >
                        {f.level_label}
                      </text>
                    </g>
                  );
                })}
            </svg>
          )}
        </div>
      </div>
      <p className="border-t border-white/10 px-3 py-2 text-xs text-slate-400">
        Boxes mark where the model located each level, colored by its grade. Select a box or a level
        to inspect it.
      </p>
    </section>
  );
}

function ToolButton({
  label,
  onClick,
  active,
  children,
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={clsx(
        "rounded-md p-1.5 text-slate-300 hover:bg-white/10 hover:text-white",
        active === false && "opacity-60",
      )}
    >
      {children}
    </button>
  );
}
