"use client";

import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";
import {
  AlertCircle,
  Brain,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileArchive,
  ImageIcon,
  X,
} from "lucide-react";
import type { ChatMessage, ImageElement, ScanAttachment, ToolCall } from "./types";

const seconds = (value?: number | null) =>
  value == null ? "" : value < 10 ? `${value.toFixed(1)} s` : `${Math.round(value)} s`;

/** DeepSeek-style reasoning disclosure. Rendered only when the model sent its thinking. */
export function Thinking({ message }: { message: ChatMessage }) {
  const live = message.status === "streaming" && message.reasoning_seconds == null;
  const [open, setOpen] = useState(message.status === "streaming");
  if (!message.reasoning) return null;
  return (
    <div className="mb-3">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-lg bg-bone px-2.5 py-1 text-sm text-graphite hover:text-ink"
      >
        <Brain size={15} className={clsx(live && "animate-pulse text-cobalt")} />
        <span>
          {live
            ? "Thinking…"
            : message.reasoning_seconds != null
              ? `Thought for ${seconds(message.reasoning_seconds)}`
              : "Thought process"}
        </span>
        <ChevronDown size={14} className={clsx("transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div
          className="mt-2 max-h-80 overflow-y-auto whitespace-pre-wrap border-l-2 border-rule pl-3 text-sm leading-relaxed text-graphite"
          dir="auto"
        >
          {message.reasoning.trim()}
        </div>
      )}
    </div>
  );
}

function ScanAnimationDot() {
  return (
    <span className="relative flex h-2.5 w-2.5" aria-hidden>
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cobalt opacity-60" />
      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-cobalt" />
    </span>
  );
}

/** While the models run on an attached scan: the scan comes into focus as the steps progress. */
function ScanReveal({ tool }: { tool: ToolCall }) {
  const progress = Math.max(0, Math.min(100, tool.progress));
  const blur = Math.round(22 - (progress / 100) * 18);
  return (
    <div className="relative mb-3 aspect-square w-full max-w-[420px] overflow-hidden rounded-2xl bg-film">
      {tool.preview ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={`data:image/jpeg;base64,${tool.preview}`}
          alt=""
          className="h-full w-full scale-110 object-contain transition-[filter] duration-700"
          style={{ filter: `blur(${blur}px) brightness(0.75) saturate(0)` }}
        />
      ) : (
        <span className="absolute inset-0 flex flex-col items-center justify-center gap-4">
          {[0, 1, 2, 3, 4].map((i) => (
            <span key={i} className="h-5 w-24 rounded bg-white/15" />
          ))}
        </span>
      )}
      <span className="reveal-shimmer absolute inset-0" aria-hidden />
      <span
        aria-hidden
        className="reveal-sweep absolute inset-x-0 h-[3px] bg-cobalt shadow-[0_0_18px_6px_rgba(43,89,195,0.55)]"
      />
      <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-film/90 to-transparent px-4 pb-3 pt-10 text-white">
        <span className="flex items-baseline justify-between gap-3 text-sm">
          <span className="truncate">{tool.message}</span>
          <span className="font-semibold tabular-nums">{progress}%</span>
        </span>
        <span className="mt-2 block h-1 overflow-hidden rounded-full bg-white/20">
          <span
            className="block h-full rounded-full bg-white transition-[width] duration-500"
            style={{ width: `${Math.max(3, progress)}%` }}
          />
        </span>
      </span>
    </div>
  );
}

/** A tool the app ran for this answer: scan analysis (animated while running) or images shown. */
export function ToolCard({ tool }: { tool: ToolCall }) {
  const running = tool.status === "running";
  const failed = tool.status === "error";
  const analysis = tool.name === "analyze_scan";
  if (analysis && running) {
    return (
      <div role="status">
        <p className="mb-2 flex items-center gap-2 text-sm font-semibold">
          <ScanAnimationDot />
          {tool.label}
        </p>
        <ScanReveal tool={tool} />
      </div>
    );
  }
  return (
    <div
      className={clsx(
        "mb-3 flex items-center gap-3 rounded-xl border bg-paper p-3",
        failed ? "border-sev-severe/40" : "border-rule",
      )}
    >
      <span
        className={clsx(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
          failed ? "bg-sev-severe/10 text-sev-severe-ink" : "bg-cobalt-wash text-cobalt-deep",
        )}
      >
        {failed ? (
          <AlertCircle size={18} />
        ) : analysis ? (
          <Check size={18} />
        ) : (
          <ImageIcon size={18} />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">{tool.label}</p>
        <p className={clsx("text-sm", failed ? "text-sev-severe-ink" : "text-graphite")}>
          {tool.message}
        </p>
        {analysis && tool.status === "done" && tool.seconds != null && (
          <p className="mt-1 text-xs text-graphite">
            {seconds(tool.seconds)} in total
            {tool.queue_seconds != null
              ? `, ${seconds(tool.queue_seconds)} waiting in the queue`
              : ""}
            {tool.model_seconds != null ? `, ${seconds(tool.model_seconds)} model run` : ""}
          </p>
        )}
      </div>
    </div>
  );
}

function Lightbox({
  images,
  index,
  onIndex,
  onClose,
}: {
  images: ImageElement[];
  index: number;
  onIndex: (index: number) => void;
  onClose: () => void;
}) {
  const step = useCallback(
    (delta: number) => onIndex((index + delta + images.length) % images.length),
    [images.length, index, onIndex],
  );
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") step(1);
      if (e.key === "ArrowLeft") step(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, step]);
  const image = images[index];
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={image.caption}
      className="fixed inset-0 z-50 flex flex-col bg-film/95 p-4 text-white"
      onClick={onClose}
    >
      <div className="flex items-center gap-3" onClick={(e) => e.stopPropagation()}>
        <p className="min-w-0 flex-1 truncate text-sm">
          {image.caption}
          <span className="ml-2 text-white/60">
            {index + 1} of {images.length}
          </span>
        </p>
        <button
          type="button"
          autoFocus
          aria-label="Close"
          className="rounded-lg p-2 hover:bg-white/10"
          onClick={onClose}
        >
          <X size={20} />
        </button>
      </div>
      <div className="flex min-h-0 flex-1 items-center justify-center gap-2">
        {images.length > 1 && (
          <button
            type="button"
            aria-label="Previous image"
            className="rounded-full p-2 hover:bg-white/10"
            onClick={(e) => {
              e.stopPropagation();
              step(-1);
            }}
          >
            <ChevronLeft size={28} />
          </button>
        )}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={`data:image/jpeg;base64,${image.data}`}
          alt={image.caption}
          className="max-h-full min-w-0 max-w-full object-contain"
          onClick={(e) => e.stopPropagation()}
        />
        {images.length > 1 && (
          <button
            type="button"
            aria-label="Next image"
            className="rounded-full p-2 hover:bg-white/10"
            onClick={(e) => {
              e.stopPropagation();
              step(1);
            }}
          >
            <ChevronRight size={28} />
          </button>
        )}
      </div>
    </div>
  );
}

/** Images attached to an answer: annotated slice first and larger, then focus map and crop. */
export function ImageElements({ images }: { images: ImageElement[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!images.length) return null;
  return (
    <>
      <div className="my-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
        {images.map((image, index) => (
          <figure
            key={image.key}
            className={clsx(
              "flex flex-col overflow-hidden rounded-xl border border-rule bg-paper",
              index === 0 && "col-span-2 sm:row-span-2",
            )}
          >
            <button
              type="button"
              className="block min-h-0 w-full flex-1 bg-film"
              onClick={() => setOpen(index)}
              aria-label={`Enlarge: ${image.caption}`}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`data:image/jpeg;base64,${image.data}`}
                alt={image.caption}
                className={clsx(
                  "w-full object-contain",
                  index === 0 ? "aspect-square sm:h-full sm:aspect-auto" : "aspect-[4/3]",
                )}
              />
            </button>
            <figcaption className="px-2 py-1.5 text-xs text-graphite">{image.caption}</figcaption>
          </figure>
        ))}
      </div>
      {open != null && (
        <Lightbox images={images} index={open} onIndex={setOpen} onClose={() => setOpen(null)} />
      )}
    </>
  );
}

export function ScanChip({ attachment }: { attachment: ScanAttachment }) {
  return (
    <span className="mb-2 flex items-center gap-2 rounded-xl bg-paper/70 p-2 text-sm">
      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-film text-white">
        <FileArchive size={16} />
      </span>
      <span className="min-w-0">
        <span className="block truncate font-medium">{attachment.name}</span>
        <span className="block text-xs text-graphite">
          {attachment.kind === "multi" ? "DICOM series" : "DICOM slice"} for analysis
        </span>
      </span>
    </span>
  );
}
