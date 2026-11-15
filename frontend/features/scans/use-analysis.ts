"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, apiUrl } from "@/lib/api";
import type { AnalysisResult, JobStatus, ScanMode } from "./types";

type Phase =
  | { name: "idle" }
  | { name: "uploading"; progress: number }
  | { name: "processing"; job: JobStatus }
  | { name: "done"; jobId: string; result: AnalysisResult }
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
    async (jobId: string, token: number) => {
      let delay = 600;
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
          setPhase({ name: "done", jobId, result: job.result });
          return;
        }
        if (job.state === "failed") {
          sessionStorage.removeItem(storageKey(mode));
          setPhase({ name: "error", message: job.error || "Analysis failed." });
          return;
        }
        setPhase({ name: "processing", job });
        await new Promise((resolve) => setTimeout(resolve, delay));
        delay = Math.min(1500, delay + 150);
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
        const { job_id } = await upload(mode, files, (progress) => {
          if (run.current === token) setPhase({ name: "uploading", progress });
        });
        sessionStorage.setItem(storageKey(mode), job_id);
        await poll(job_id, token);
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
