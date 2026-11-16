"""The unit of work executed by Celery workers and by the in-process fallback queue."""

from __future__ import annotations

import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)
KINDS = ("single", "multi")

# Progress messages start with one of these; consecutive messages of a stage are summed.
# The names match the steps shown in the web app's progress list.
STAGE_NAMES = (
    ("Reading", "Read and de-identify"),
    ("Detecting", "Detect levels"),
    ("Stage 1", "Locate levels in 3D"),
    ("Stage 2", "Refine positions"),
    ("Stage 3", "Grade each level"),
    ("Grading", "Grade each level"),
    ("Rendering", "Render slices"),
    ("Preparing", "Prepare results"),
)


class JobError(RuntimeError):
    """A failure whose message is safe to show to the user."""


def stage_name(message: str) -> str:
    return next((name for prefix, name in STAGE_NAMES if message.startswith(prefix)), "Other")


class StageClock:
    """Turns the pipeline's progress messages into per-stage durations.

    Each progress update also carries the timing so far, so the web app can show the time
    of every finished step and a running clock on the current one.
    """

    def __init__(self, progress):
        self.progress = progress
        self.marks: list[tuple[float, str]] = []

    def __call__(self, value: int, message: str) -> None:
        now = time.time()
        name = stage_name(message)
        if not self.marks or self.marks[-1][1] != name:
            self.marks.append((now, name))
        done = self.stages(self.marks[-1][0])[:-1] if len(self.marks) > 1 else []
        timing = {"stages": done, "stage": name, "stage_started_at": self.marks[-1][0]}
        self.progress(value, message, timing)

    def stages(self, finished: float) -> list[dict]:
        totals: dict[str, float] = {}
        ends = [mark[0] for mark in self.marks[1:]] + [finished]
        for (start, name), end in zip(self.marks, ends, strict=True):
            totals[name] = totals.get(name, 0.0) + (end - start)
        return [{"name": name, "seconds": round(seconds, 3)} for name, seconds in totals.items()]


def analyze_upload(
    kind: str, upload_path: str, progress, submitted_at: float | None = None
) -> dict:
    """`progress(value, message, timing)` receives the step timing so far as a third argument."""
    started = time.time()
    if kind not in KINDS:
        raise JobError(f"Unknown analysis kind: {kind}")
    path = Path(upload_path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise JobError("The uploaded file is no longer available. Please upload it again.") from exc
    finally:
        path.unlink(missing_ok=True)  # uploads never outlive their job

    from app.ml.dicom import UnsupportedScan
    from app.ml.registry import ModelUnavailable

    clock = StageClock(progress)
    try:
        if kind == "single":
            from app.ml.pipelines.single import run_single

            result = run_single(data, clock)
        else:
            from app.ml.pipelines.series import run_series

            result = run_series(data, clock)
    except (UnsupportedScan, ModelUnavailable) as exc:
        raise JobError(str(exc)) from exc
    except Exception as exc:
        log.exception("analysis failed (%s)", kind)
        raise JobError(
            "Analysis failed unexpectedly. Check the scan format and try again."
        ) from exc
    finished = time.time()
    result["timings"] = {
        "submitted_at": submitted_at,
        "started_at": started,
        "finished_at": finished,
        "queue_seconds": round(max(0.0, started - submitted_at), 3) if submitted_at else None,
        "model_seconds": round(finished - started, 3),
        "stages": clock.stages(finished),
    }
    return result
