"use client";

import { useEffect, useState } from "react";
import type { ClientTimings, JobStatus, ServerTimings, StageTime } from "./types";

export const formatSeconds = (seconds: number) =>
  seconds < 1 ? `${Math.round(seconds * 1000)} ms` : `${seconds.toFixed(seconds < 10 ? 2 : 1)} s`;

/** Re-renders every 100 ms while `active`, so running clocks tick between polls. */
export function useTicker(active: boolean) {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(performance.now()), 100);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

/** Live step times during an analysis: finished steps and a running clock on the current one. */
export function liveStepTimes(job: JobStatus | null, received: number, now: number) {
  const times = new Map<string, number>(
    (job?.timing?.stages ?? []).map((s) => [s.name, s.seconds]),
  );
  const current = job?.timing?.stage ?? null;
  if (current && job?.timing)
    times.set(current, job.timing.stage_elapsed + Math.max(0, now - received) / 1000);
  return { times, current };
}

/** The finished analysis: the same numbered steps as the progress list, each with its time. */
export function StepTimings({
  steps,
  server,
  client,
}: {
  steps: string[];
  server?: ServerTimings;
  client: ClientTimings;
}) {
  if (!server) return null;
  const byName = new Map<string, number>(server.stages.map((s: StageTime) => [s.name, s.seconds]));
  const queue = server.queue_seconds;
  const { upload_seconds: upload, total_seconds: total } = client;
  const returned =
    total != null && upload != null
      ? Math.max(0, total - upload - (queue ?? 0) - server.model_seconds)
      : null;
  const extras = [
    upload != null ? `upload ${formatSeconds(upload)}` : null,
    queue != null ? `waiting in the queue ${formatSeconds(queue)}` : null,
    `model run ${formatSeconds(server.model_seconds)}`,
    returned != null ? `result returned ${formatSeconds(returned)}` : null,
  ].filter(Boolean);
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
      <ol className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {steps.map((name, index) => (
          <li key={name} className="flex items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-cobalt text-[11px] font-bold text-white">
              {index + 1}
            </span>
            <span>{name}</span>
            {byName.has(name) && (
              <span className="font-semibold tabular-nums">
                {formatSeconds(byName.get(name) ?? 0)}
              </span>
            )}
          </li>
        ))}
      </ol>
      <p className="text-graphite">
        <span className="font-semibold text-ink tabular-nums">
          {formatSeconds(total ?? server.model_seconds + (queue ?? 0))}
        </span>{" "}
        total, {extras.join(", ")}
      </p>
    </div>
  );
}
