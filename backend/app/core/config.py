"""Runtime settings read once from the environment (and `backend/.env` when present)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]

# `backend/.env` is the documented location; `backend/app/.env` is read for older checkouts.
for candidate in (BACKEND_DIR / ".env", BACKEND_DIR / "app" / ".env"):
    if candidate.is_file():
        load_dotenv(candidate, override=False)


def _list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    path = Path(value) if value else default
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


def _models(provider: str, fallback: str) -> list[str]:
    """`GROQ_MODELS=a,b` wins; the older single `GROQ_MODEL` setting stays supported."""
    models = _list(f"{provider}_MODELS")
    single = os.getenv(f"{provider}_MODEL", "").strip()
    if single and single not in models:
        models.insert(0, single)
    return models or [fallback]


@dataclass(frozen=True)
class Settings:
    app_name: str = "Lumber Spine AI"
    version: str = "3.0.0"
    environment: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))

    model_dir: Path = field(default_factory=lambda: _path("MODEL_DIR", BACKEND_DIR / "model"))
    data_dir: Path = field(default_factory=lambda: _path("DATA_DIR", BACKEND_DIR / "data"))
    max_upload_mb: int = field(default_factory=lambda: _int("MAX_UPLOAD_MB", 120))

    allowed_origins: list[str] = field(
        default_factory=lambda: _list(
            "FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        )
    )

    # Background jobs: "auto" uses Celery when Redis answers, otherwise an in-process queue.
    job_backend: str = field(default_factory=lambda: os.getenv("JOB_BACKEND", "auto").lower())
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", ""))
    job_ttl_seconds: int = field(default_factory=lambda: _int("JOB_TTL_SECONDS", 3600))
    task_time_limit_seconds: int = field(
        default_factory=lambda: _int("TASK_TIME_LIMIT_SECONDS", 900)
    )

    # Chat providers and automatic fallback order.
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip())
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", "").strip())
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "").strip().rstrip("/")
    )
    ollama_api_key: str = field(default_factory=lambda: os.getenv("OLLAMA_API_KEY", "").strip())
    gemini_models: list[str] = field(default_factory=lambda: _models("GEMINI", "gemini-2.5-flash"))
    groq_models: list[str] = field(
        default_factory=lambda: _models("GROQ", "llama-3.3-70b-versatile")
    )
    ollama_models: list[str] = field(default_factory=lambda: _models("OLLAMA", "gemma3:4b"))
    llm_fallback_order: list[str] = field(
        default_factory=lambda: _list("LLM_FALLBACK_ORDER", "groq,gemini,ollama")
    )
    llm_timeout_seconds: int = field(default_factory=lambda: _int("LLM_TIMEOUT_SECONDS", 90))

    # Local single-reviewer case library.
    review_access_token: str = field(
        default_factory=lambda: os.getenv("REVIEW_ACCESS_TOKEN", "").strip()
    )
    reviewer_name: str = field(
        default_factory=lambda: os.getenv("REVIEWER_NAME", "Configured reviewer").strip()
    )

    # Requests per minute per client for expensive endpoints (0 disables).
    rate_limit_per_minute: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 30))

    @property
    def upload_dir(self) -> Path:
        return _path("UPLOAD_DIR", self.data_dir / "uploads")

    @property
    def database_path(self) -> Path:
        return self.data_dir / "workspace.sqlite3"

    @property
    def calibration_file(self) -> Path:
        return _path("CALIBRATION_FILE", self.data_dir / "validation.json")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
