"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import clsx from "clsx";
import {
  CheckCircle2,
  FileArchive,
  FileDown,
  FileImage,
  Loader2,
  MessageSquareText,
  RotateCcw,
  Save,
  UploadCloud,
} from "lucide-react";
import { api, apiUrl, jsonBody } from "@/lib/api";
import { SEVERITIES, styleFor } from "@/lib/severity";
import { GradeDistribution, LevelProfileChart } from "./charts";
import FilmViewer from "./film-viewer";
import FindingDetail, { SeverityBadge } from "./finding-detail";
import Recommendations from "./recommendations";
import SaveCaseDialog from "./save-case-dialog";
import SpineLadder from "./spine-ladder";
import type { AnalysisResult, ClientTimings, JobStatus, ScanMode } from "./types";
import { StepTimings, formatSeconds, liveStepTimes, useTicker } from "./request-timing";
import { useAnalysis } from "./use-analysis";

const COPY: Record<
  ScanMode,
  { title: string; intro: string; accept: string; hint: string[]; stages: [number, string][] }
> = {
  single: {
    title: "Grade a single slice",
    intro:
      "Upload one lumbar MRI slice. The level detector finds each disc level, and every level is graded for the condition its sequence shows.",
    accept: ".dcm,application/dicom",
    hint: [
      "One .dcm file, up to 120 MB",
      "Sagittal T1 grades foraminal narrowing",
      "Sagittal T2 or STIR grades canal stenosis",
      "Axial T2 grades subarticular stenosis",
    ],
    stages: [
      [5, "Read and de-identify"],
      [20, "Detect levels"],
      [30, "Grade each level"],
      [92, "Prepare results"],
    ],
  },
  multi: {
    title: "Grade a full series",
    intro:
      "Upload a ZIP with every slice of one series. Three models locate the levels in 3D, refine their position and grade each level.",
    accept: ".zip,application/zip",
    hint: [
      "A ZIP, a folder or the .dcm slices of one series, up to 120 MB",
      "Sagittal T1, sagittal T2/STIR or axial T2",
      "Identifiers are removed in memory",
      "Uploads are deleted after analysis",
    ],
    stages: [
      [5, "Read and de-identify"],
      [20, "Locate levels in 3D"],
      [45, "Refine positions"],
      [55, "Grade each level"],
      [93, "Render slices"],
    ],
  },
};

export default function ScanStudio({ mode }: { mode: ScanMode }) {
  const { phase, start, reset } = useAnalysis(mode);
  const copy = COPY[mode];

  return (
    <div className="mx-auto max-w-[90rem] px-4 pb-16 pt-8 sm:px-6">
      {phase.name === "done" ? (
        <Results
          result={phase.result}
          jobId={phase.jobId}
          timing={phase.timing}
          steps={copy.stages.map(([, label]) => label)}
          onReset={reset}
        />
      ) : (
        <div className="grid gap-8 lg:grid-cols-[1fr_1.15fr] lg:items-start">
          <div className="max-w-xl pt-2">
            <h1 className="text-[2.1rem] font-bold leading-tight tracking-tight">{copy.title}</h1>
            <p className="mt-3 text-lg leading-relaxed text-graphite">{copy.intro}</p>
            <ul className="mt-6 space-y-2.5">
              {copy.hint.map((line) => (
                <li key={line} className="flex items-start gap-2.5">
                  <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-cobalt" />
                  {line}
                </li>
              ))}
            </ul>
          </div>
          {phase.name === "idle" || phase.name === "error" ? (
            <Dropzone
              mode={mode}
              accept={copy.accept}
              error={phase.name === "error" ? phase.message : undefined}
              onFile={start}
            />
          ) : (
            <Progress
              stages={copy.stages}
              uploading={phase.name === "uploading" ? phase.progress : null}
              job={phase.name === "processing" ? phase.job : null}
              received={phase.name === "processing" ? phase.received : 0}
              uploadSeconds={phase.name === "processing" ? phase.upload_seconds : null}
              queuedSince={phase.name === "processing" ? phase.queued_since : null}
              onCancel={reset}
            />
          )}
        </div>
      )}
    </div>
  );
}

const IMAGE_TYPES = /\.(png|jpe?g|webp|bmp|gif|tiff?)$/i;

function Dropzone({
  mode,
  accept,
  error,
  onFile,
}: {
  mode: ScanMode;
  accept: string;
  error?: string;
  onFile: (files: File[]) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [local, setLocal] = useState("");
  const Icon = mode === "multi" ? FileArchive : FileImage;

  useEffect(() => {
    // Folder picking is a non-standard attribute, so it is set on the element directly.
    folder.current?.setAttribute("webkitdirectory", "");
  }, []);

  function choose(list: FileList | File[] | null | undefined) {
    setLocal("");
    const picked = Array.from(list ?? []).filter(
      (f) => !f.name.startsWith(".") && f.name.toLowerCase() !== "dicomdir",
    );
    if (!picked.length) return;
    if (picked.some((f) => IMAGE_TYPES.test(f.name))) {
      setFiles([]);
      setLocal(
        "PNG and JPG images cannot be graded: the models need DICOM (.dcm) files, which record the plane and sequence. Export the scan as DICOM, or ask about a picture in the Assistant.",
      );
      return;
    }
    const zips = picked.filter((f) => f.name.toLowerCase().endsWith(".zip"));
    const dicoms = picked.filter((f) => !f.name.toLowerCase().endsWith(".zip"));
    let next: File[] = [];
    if (mode === "single") {
      if (picked.length !== 1 || zips.length) {
        setLocal(
          "Choose one .dcm file here. For a ZIP or several slices, use Full series instead.",
        );
        setFiles([]);
        return;
      }
      next = picked;
    } else if (zips.length === 1 && picked.length === 1) {
      next = zips;
    } else if (!zips.length && dicoms.length >= 3) {
      next = dicoms;
    } else {
      setFiles([]);
      setLocal(
        zips.length
          ? "Choose one ZIP, or the slices themselves, not both."
          : "A series needs at least 3 DICOM slices. For one file, use Single slice.",
      );
      return;
    }
    const size = next.reduce((total, f) => total + f.size, 0);
    if (size > 120 * 1024 * 1024) {
      setFiles([]);
      setLocal("The upload is larger than 120 MB. Upload one series at a time.");
      return;
    }
    setFiles(next);
  }

  const message = local || error;
  const size = files.reduce((total, f) => total + f.size, 0);
  return (
    <div className="panel p-3">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          choose(event.dataTransfer.files);
        }}
        className={clsx(
          "film flex min-h-[320px] flex-col items-center justify-center gap-4 border-2 border-dashed p-8 text-center transition-colors",
          dragging ? "border-cobalt bg-film-2" : "border-white/15",
        )}
      >
        <UploadCloud size={40} className="text-slate-300" />
        <div>
          <p className="text-lg font-semibold text-white">
            {mode === "multi"
              ? "Drop a series ZIP or its DICOM slices here"
              : "Drop a DICOM slice here"}
          </p>
          <p className="mt-1 text-sm text-slate-400">or choose from your computer</p>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          <button type="button" className="btn btn-quiet" onClick={() => input.current?.click()}>
            {mode === "multi" ? "Choose ZIP or files" : "Choose file"}
          </button>
          {mode === "multi" && (
            <button type="button" className="btn btn-quiet" onClick={() => folder.current?.click()}>
              Choose folder
            </button>
          )}
        </div>
        <input
          ref={input}
          type="file"
          accept={mode === "multi" ? ".zip,.dcm,application/zip,application/dicom" : accept}
          multiple={mode === "multi"}
          className="sr-only"
          onChange={(event) => {
            choose(event.target.files);
            event.target.value = "";
          }}
        />
        <input
          ref={folder}
          type="file"
          className="sr-only"
          onChange={(event) => {
            choose(event.target.files);
            event.target.value = "";
          }}
        />
      </div>
      {files.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl bg-bone p-3">
          <Icon size={22} className="text-cobalt" />
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold">
              {files.length === 1 ? files[0].name : `${files.length} DICOM slices`}
            </p>
            <p className="text-sm text-graphite">{(size / 1024 / 1024).toFixed(1)} MB</p>
          </div>
          <button type="button" className="btn btn-primary" onClick={() => onFile(files)}>
            Analyze {mode === "multi" ? "series" : "slice"}
          </button>
        </div>
      )}
      {message && (
        <p
          role="alert"
          className="mt-3 rounded-lg bg-sev-severe/10 p-3 text-sm text-sev-severe-ink"
        >
          {message}
        </p>
      )}
    </div>
  );
}

function Progress({
  stages,
  uploading,
  job,
  received,
  uploadSeconds,
  queuedSince,
  onCancel,
}: {
  stages: [number, string][];
  uploading: number | null;
  job: JobStatus | null;
  received: number;
  uploadSeconds: number | null;
  queuedSince: number | null;
  onCancel: () => void;
}) {
  const value = uploading !== null ? Math.round(uploading * 0.05) : Math.max(5, job?.progress ?? 0);
  const queued = job?.state === "queued";
  const now = useTicker(uploading === null && !!job);
  const { times, current } = liveStepTimes(job, received, now);
  const finished = new Set(job?.timing?.stages.map((s) => s.name) ?? []);
  return (
    <section className="panel p-6" aria-live="polite">
      <div className="flex items-center gap-3">
        <Loader2 className="animate-spin text-cobalt" size={22} />
        <p className="text-lg font-semibold">
          {uploading !== null ? `Uploading ${uploading}%` : job?.message || "Working"}
        </p>
      </div>
      <div className="mt-5 h-2 overflow-hidden rounded-full bg-bone">
        <div
          className="h-full rounded-full bg-cobalt transition-[width] duration-500"
          style={{ width: `${value}%` }}
        />
      </div>
      {(uploadSeconds !== null || queued) && (
        <p className="mt-4 text-sm text-graphite">
          {uploadSeconds !== null && <>Uploaded in {formatSeconds(uploadSeconds)}</>}
          {queued && queuedSince !== null && (
            <>
              {uploadSeconds !== null ? ", " : ""}waiting in the queue{" "}
              <span className="tabular-nums">{formatSeconds((now - queuedSince) / 1000)}</span>
            </>
          )}
        </p>
      )}
      <ol className="mt-5 space-y-3">
        {stages.map(([at, label], index) => {
          const next = stages[index + 1]?.[0] ?? 101;
          const state = job?.timing
            ? finished.has(label)
              ? "done"
              : current === label
                ? "active"
                : "todo"
            : value >= next
              ? "done"
              : value >= at && uploading === null
                ? "active"
                : "todo";
          const seconds = times.get(label);
          return (
            <li key={label} className="flex items-center gap-3">
              <span
                className={clsx(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                  state === "done" && "bg-cobalt text-white",
                  state === "active" && "bg-cobalt-wash text-cobalt-deep ring-2 ring-cobalt",
                  state === "todo" && "bg-bone text-graphite",
                )}
              >
                {index + 1}
              </span>
              <span className={state === "todo" ? "text-graphite" : "font-medium"}>{label}</span>
              {seconds !== undefined && state !== "todo" && (
                <span
                  className={clsx(
                    "ml-auto tabular-nums",
                    state === "active" ? "text-cobalt-deep" : "font-semibold",
                  )}
                >
                  {formatSeconds(seconds)}
                </span>
              )}
            </li>
          );
        })}
      </ol>
      {queued && (
        <p className="mt-5 text-sm text-graphite">
          Waiting for an analysis worker. If this does not change, start the worker (see the
          README).
        </p>
      )}
      <button type="button" className="btn btn-quiet mt-6" onClick={onCancel}>
        Stop waiting
      </button>
    </section>
  );
}

/** Downscale a base64 PNG to a JPEG of at most `side` pixels (for the chat attachment card). */
function shrink(png: string, side: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const scale = Math.min(1, side / Math.max(image.width, image.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(image.width * scale);
      canvas.height = Math.round(image.height * scale);
      canvas.getContext("2d")?.drawImage(image, 0, 0, canvas.width, canvas.height);
      resolve(canvas.toDataURL("image/jpeg", 0.85).split(",", 2)[1] ?? "");
    };
    image.onerror = () => reject(new Error("The preview image could not be prepared."));
    image.src = `data:image/png;base64,${png}`;
  });
}

/** Annotated slices, model crops and focus maps the assistant can show when asked. */
async function chatAssets(result: AnalysisResult) {
  const used = new Set(result.findings.map((f) => f.image_index));
  const assets: { key: string; caption: string; image: string }[] = [];
  for (const image of result.images.filter((img) => used.has(img.index)).slice(0, 12)) {
    assets.push({
      key: `slice:${image.index}`,
      caption: `${image.slice_number ? `Slice ${image.slice_number}` : "Image"} with level boxes`,
      image: await shrink(image.annotated, 900),
    });
  }
  for (const f of result.findings) {
    const name = `${f.id} ${f.level_label}, ${f.severity}`;
    if (f.explanation.heatmap_image)
      assets.push({
        key: `focus:${f.id}`,
        caption: `Focus map ${name}`,
        image: await shrink(f.explanation.heatmap_image, 400),
      });
    if (f.explanation.crop_image)
      assets.push({
        key: `crop:${f.id}`,
        caption: `Model input ${name}`,
        image: await shrink(f.explanation.crop_image, 400),
      });
  }
  return assets.slice(0, 60);
}

function Results({
  result,
  jobId,
  timing,
  steps,
  onReset,
}: {
  result: AnalysisResult;
  jobId: string;
  timing: ClientTimings;
  steps: string[];
  onReset: () => void;
}) {
  const router = useRouter();
  const findings = result.findings;
  const [selectedId, setSelectedId] = useState<string | undefined>(
    () =>
      [...findings].sort(
        (a, b) => SEVERITIES.indexOf(b.severity) - SEVERITIES.indexOf(a.severity),
      )[0]?.id,
  );
  const selected = findings.find((f) => f.id === selectedId);
  const [imageIndex, setImageIndex] = useState(selected?.image_index ?? 0);
  const [saving, setSaving] = useState(false);
  const [asking, setAsking] = useState(false);
  const [notice, setNotice] = useState("");
  const sided = result.condition !== "SCS";

  useEffect(() => {
    if (selected) setImageIndex(selected.image_index);
  }, [selected]);

  const select = (id: string) => setSelectedId(id);
  const worst = result.summary.max_severity;
  const headline = useMemo(() => {
    const { counts } = result.summary;
    if (!findings.length) return "No levels were graded";
    if (counts.Severe) return `${counts.Severe} level${counts.Severe > 1 ? "s" : ""} graded severe`;
    if (counts.Moderate)
      return `${counts.Moderate} level${counts.Moderate > 1 ? "s" : ""} graded moderate`;
    return "All assessed levels graded normal or mild";
  }, [result.summary, findings.length]);

  async function askAssistant() {
    setAsking(true);
    try {
      const image = result.images[selected?.image_index ?? 0] ?? result.images[0];
      const thread = await api<{ id: string }>(
        "/api/chat/threads",
        jsonBody({
          title: `${result.condition_name} result`,
          case_context: {
            condition: result.condition,
            condition_name: result.condition_name,
            plane: result.plane,
            sequence: result.sequence,
            mode: result.mode,
            // Focus maps stay in the browser; the model only receives structured findings.
            findings: findings.map(({ explanation: _drop, ...rest }) => rest),
            // Sizes only (for box coordinates); the pixels are sent separately as assets.
            images: result.images.map(({ index, slice_number, width, height }) => ({
              index,
              slice_number,
              width,
              height,
            })),
            quality: result.quality,
            recommendations: result.recommendations,
          },
          preview_image: image ? await shrink(image.annotated, 720) : null,
          assets: await chatAssets(result),
        }),
      );
      router.push(`/assistant?thread=${thread.id}`);
    } catch (error) {
      setNotice((error as Error).message);
      setAsking(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-graphite">
            {result.condition_name}, {result.plane.toLowerCase()} {result.sequence}
            {result.slice_count ? `, ${result.slice_count} slices` : ""}
          </p>
          <h1 className="mt-1 flex flex-wrap items-center gap-3 text-[2rem] font-bold leading-tight tracking-tight">
            {headline}
            {worst && <SeverityBadge severity={worst} size="lg" />}
          </h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <a className="btn btn-quiet" href={apiUrl(`/api/jobs/${jobId}/report.pdf`)}>
            <FileDown size={17} /> PDF report
          </a>
          <button className="btn btn-quiet" onClick={() => setSaving(true)}>
            <Save size={17} /> Save to cases
          </button>
          <button className="btn btn-quiet" onClick={askAssistant} disabled={asking}>
            <MessageSquareText size={17} /> Ask the assistant
          </button>
          <button className="btn btn-primary" onClick={onReset}>
            <RotateCcw size={17} /> New scan
          </button>
        </div>
      </header>
      {result.timings && (
        <div className="rounded-xl border border-rule bg-paper px-4 py-3">
          <StepTimings steps={steps} server={result.timings} client={timing} />
        </div>
      )}
      {notice && (
        <p role="status" className="rounded-lg bg-cobalt-wash p-3 text-sm text-cobalt-deep">
          {notice}
        </p>
      )}

      <div className="grid gap-5 xl:grid-cols-[260px_minmax(0,1fr)_380px]">
        <aside className="panel order-2 p-4 xl:order-1">
          <h2 className="font-semibold">Levels</h2>
          <p className="mb-3 text-sm text-graphite">
            Colored by grade. A dot marks a level to double-check.
          </p>
          <SpineLadder
            findings={findings}
            sided={sided}
            selectedId={selectedId}
            onSelect={(f) => select(f.id)}
          />
          <ul className="mt-4 space-y-1.5 text-sm">
            {SEVERITIES.map((s) => (
              <li key={s} className="flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <span className="h-3 w-3 rounded" style={{ background: styleFor(s).fill }} />
                  {s}
                </span>
                <span className="font-semibold tabular-nums">{result.summary.counts[s] ?? 0}</span>
              </li>
            ))}
            {result.summary.not_assessed.length > 0 && (
              <li className="flex items-center justify-between text-graphite">
                <span className="flex items-center gap-2">
                  <span className="h-3 w-3 rounded border border-rule bg-bone" />
                  Not assessed
                </span>
                <span className="font-semibold tabular-nums">
                  {result.summary.not_assessed.length}
                </span>
              </li>
            )}
          </ul>
        </aside>
        <div className="order-1 min-w-0 xl:order-2">
          <FilmViewer
            images={result.images}
            findings={findings}
            imageIndex={imageIndex}
            onImageChange={setImageIndex}
            selectedId={selectedId}
            onSelect={(f) => select(f.id)}
          />
        </div>
        <div className="order-3">
          <FindingDetail finding={selected} />
        </div>
      </div>

      {findings.length > 0 && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <LevelProfileChart
            findings={findings}
            selectedId={selectedId}
            onSelect={(f) => select(f.id)}
          />
          <GradeDistribution summary={result.summary} />
        </div>
      )}

      <Recommendations
        items={result.recommendations}
        findings={findings}
        onSelect={(f) => {
          select(f.id);
          window.scrollTo({ top: 0, behavior: "smooth" });
        }}
      />

      <details className="panel p-5">
        <summary className="cursor-pointer font-semibold">
          Image checks and model details
          {result.quality.status === "review" && (
            <span className="ml-2 text-sm font-normal text-sev-moderate-ink">
              {result.quality.issues.length} check{result.quality.issues.length === 1 ? "" : "s"} to
              review
            </span>
          )}
        </summary>
        <div className="mt-4 grid gap-6 text-sm md:grid-cols-2">
          <div>
            <h3 className="font-semibold">Image checks</h3>
            {result.quality.issues.length === 0 && (
              <p className="mt-1 text-graphite">No basic input flags.</p>
            )}
            <ul className="mt-1 list-disc space-y-1 pl-5">
              {[...result.quality.issues, ...(result.quality.notes ?? [])].map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-graphite">{result.quality.method}</p>
          </div>
          <div>
            <h3 className="font-semibold">Model provenance</h3>
            <dl className="mt-1 space-y-1">
              <div>
                <dt className="inline text-graphite">Pipeline </dt>
                <dd className="inline">{result.provenance.pipeline_version}</dd>
              </div>
              <div>
                <dt className="inline text-graphite">Calibration </dt>
                <dd className="inline">{result.provenance.calibration}</dd>
              </div>
              {Object.entries(result.provenance.checkpoints_sha256 ?? {}).map(([name, hash]) => (
                <div key={name} className="truncate">
                  <dt className="inline text-graphite">{name} </dt>
                  <dd className="inline font-mono text-xs">{hash.slice(0, 16)}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </details>
      {saving && (
        <SaveCaseDialog
          result={result}
          onClose={(message) => {
            setSaving(false);
            if (message) setNotice(message);
          }}
        />
      )}
    </div>
  );
}
