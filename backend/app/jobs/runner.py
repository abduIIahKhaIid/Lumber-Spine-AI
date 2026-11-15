"""The unit of work executed by Celery workers and by the in-process fallback queue."""

from __future__ import annotations

import logging
from pathlib import Path

from app.ml.pipelines.common import Progress

log = logging.getLogger(__name__)
KINDS = ("single", "multi")


class JobError(RuntimeError):
    """A failure whose message is safe to show to the user."""


def analyze_upload(kind: str, upload_path: str, progress: Progress) -> dict:
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

    try:
        if kind == "single":
            from app.ml.pipelines.single import run_single

            return run_single(data, progress)
        from app.ml.pipelines.series import run_series

        return run_series(data, progress)
    except (UnsupportedScan, ModelUnavailable) as exc:
        raise JobError(str(exc)) from exc
    except Exception as exc:
        log.exception("analysis failed (%s)", kind)
        raise JobError(
            "Analysis failed unexpectedly. Check the scan format and try again."
        ) from exc
