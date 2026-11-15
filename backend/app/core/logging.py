"""Process-wide logging. Patient data, images and chat text are never logged."""

import logging
import os


def configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Third-party request logs can include URLs with query data; keep them quiet.
    for noisy in ("httpx", "httpcore", "google_genai.models", "ultralytics"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
