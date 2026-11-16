# Two images from one file:
#   api    - FastAPI producer, no torch (small, fast to start)
#   worker - Celery consumer with CPU PyTorch and the model code
# Model weights are mounted at runtime (/app/model); they are never baked into an image.
#
# Build speed: dependencies are installed in their own layers BEFORE the source code is
# copied, so editing code only rebuilds the last small layer. pip's download cache is kept
# in a BuildKit cache mount, so even a dependency change does not re-download everything.

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home /app app

# Dependency list only: a stub package lets pip resolve pyproject.toml without the code.
FROM base AS deps-api
COPY pyproject.toml README.md ./
RUN --mount=type=cache,target=/root/.cache/pip \
    mkdir -p app && touch app/__init__.py \
 && pip install . \
 && pip uninstall -y lumber-spine-ai-backend \
 && rm -rf app build *.egg-info

FROM base AS deps-worker
# OpenCV (pulled in by ultralytics) needs these shared libraries.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
 && apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0
# CPU-only PyTorch: about 2 GB smaller than the default CUDA build. Own layer, so a change
# to pyproject.toml does not reinstall it.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.14.1" "torchvision==0.29.2"
COPY pyproject.toml README.md ./
RUN --mount=type=cache,target=/root/.cache/pip \
    mkdir -p app && touch app/__init__.py \
 && pip install ".[ml]" \
 && pip uninstall -y lumber-spine-ai-backend \
 && rm -rf app build *.egg-info

FROM deps-api AS api
COPY app ./app
RUN mkdir -p /app/data /app/model && chown -R app:app /app/data
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM deps-worker AS worker
COPY app ./app
RUN mkdir -p /app/data /app/model /app/.config && chown -R app:app /app/data /app/.config
ENV YOLO_CONFIG_DIR=/app/.config
USER app
HEALTHCHECK --interval=60s --timeout=15s --start-period=60s --retries=3 \
  CMD celery -A app.worker.celery_app inspect ping --timeout 10 || exit 1
CMD ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel=info", "--concurrency=1"]
