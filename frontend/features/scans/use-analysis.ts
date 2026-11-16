"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, apiUrl } from "@/lib/api";
import type { AnalysisResult, ClientTimings, JobStatus, ScanMode } from "./types";

type Phase =
  | { name: "idle" }
  | { name: "uploading"; progress: number }
  | {
      name: "processing";
      job: JobStatus;
      /** performance.now() when this status arrived, to keep the step clock ticking. */
      received: number;
      upload_seconds: number | null;
      queued_since: number;
    }
  | { name: "done"; jobId: string; result: AnalysisResult; timing: ClientTimings }
  | { name: "error"; message: string };

const storageKey = (mode: ScanMode) => `spinescope.job.${mode}`;

function upload(mode: ScanMode, files: File[], onProgress: (value: number) => void) {
  return new Promise<{ job_id: string }>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", apiUrl(`/api/scans/${mode}`));
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    request.onload = () => {
      let body: { job_id?: string; detail?: string } = {};
      try {
        body = JSON.parse(request.responseText);
      } catch {
        /* ignore */
      }
      if (request.status === 202 && body.job_id) resolve({ job_id: body.job_id });
      else reject(new Error(body.detail || `Upload failed (${request.status}).`));
    };
    request.onerror = () =>
      reject(new Error("The analysis server is not reachable. Start the backend and try again."));
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    request.send(form);
  });
}

/** Upload -> poll the background job -> result. Restores the last job of this tab. */
export function useAnalysis(mode: ScanMode) {
  const [phase, setPhase] = useState<Phase>({ name: "idle" });
  const run = useRef(0);

  const poll = useCallback(
    async (jobId: string, token: number, clock?: { start: number; uploaded: number }) => {
      let delay = 500;
      while (run.current === token) {
        let job: JobStatus;
        try {
          job = await api<JobStatus>(`/api/jobs/${jobId}`);
        } catch (error) {
          if (run.current !== token) return;
          if (error instanceof ApiError && error.status === 404) {
            sessionStorage.removeItem(storageKey(mode));
            setPhase({ name: "idle" });
            return;
          }
          setPhase({ name: "error", message: (error as Error).message });
          return;
        }
        if (run.current !== token) return;
        if (job.state === "succeeded" && job.result) {
          const now = performance.now();
          setPhase({
            name: "done",
            jobId,
            result: job.result,
            timing: clock
              ? {
                  upload_seconds: (clock.uploaded - clock.start) / 1000,
                  total_seconds: (now - clock.start) / 1000,
                }
              : { upload_seconds: null, total_seconds: null },
          });
          return;
        }
        if (job.state === "failed") {
          sessionStorage.removeItem(storageKey(mode));
          setPhase({ name: "error", message: job.error || "Analysis failed." });
          return;
        }
        setPhase((current) => ({
          name: "processing",
          job,
          received: performance.now(),
          upload_seconds: clock ? (clock.uploaded - clock.start) / 1000 : null,
          queued_since:
            current.name === "processing"
              ? current.queued_since
              : (clock?.uploaded ?? performance.now()),
        }));
        await new Promise((resolve) => setTimeout(resolve, delay));
        delay = Math.min(1000, delay + 100);
      }
    },
    [mode],
  );

  useEffect(() => {
    const saved = sessionStorage.getItem(storageKey(mode));
    if (!saved) return;
    const token = ++run.current;
    setPhase({
      name: "processing",
      job: { id: saved, state: "queued", progress: 0, message: "Restoring the last analysis" },
      received: performance.now(),
      upload_seconds: null,
      queued_since: performance.now(),
    });
    void poll(saved, token).catch(() => setPhase({ name: "idle" }));
    return () => {
      run.current += 1;
    };
  }, [mode, poll]);

  const start = useCallback(
    async (files: File[]) => {
      const token = ++run.current;
      setPhase({ name: "uploading", progress: 0 });
      try {
        const begin = performance.now();
        const { job_id } = await upload(mode, files, (progress) => {
          if (run.current === token) setPhase({ name: "uploading", progress });
        });
        sessionStorage.setItem(storageKey(mode), job_id);
        await poll(job_id, token, { start: begin, uploaded: performance.now() });
      } catch (error) {
        if (run.current === token) setPhase({ name: "error", message: (error as Error).message });
      }
    },
    [mode, poll],
  );

  const reset = useCallback(() => {
    run.current += 1;
    sessionStorage.removeItem(storageKey(mode));
    setPhase({ name: "idle" });
  }, [mode]);

  return { phase, start, reset };
}
