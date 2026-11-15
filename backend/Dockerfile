# Two images from one file:
#   api    - FastAPI producer, no torch (small, fast to start)
#   worker - Celery consumer with CPU PyTorch and the model code
# Model weights are mounted at runtime (/app/model); they are never baked into an image.

FROM python:3.15-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home /app app
COPY pyproject.toml README.md ./
COPY app ./app

FROM base AS api
RUN pip install .
RUN mkdir -p /app/data /app/model && chown -R app:app /app/data
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM base AS worker
# OpenCV (pulled in by ultralytics) needs these shared libraries.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
# CPU-only PyTorch keeps the image ~2 GB smaller than the default CUDA build.
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.14.1" "torchvision==0.29.2" \
 && pip install ".[ml]"
RUN mkdir -p /app/data /app/model /app/.config && chown -R app:app /app/data /app/.config
ENV YOLO_CONFIG_DIR=/app/.config
USER app
HEALTHCHECK --interval=60s --timeout=15s --start-period=60s --retries=3 \
  CMD celery -A app.worker.celery_app inspect ping --timeout 10 || exit 1
CMD ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel=info", "--concurrency=1"]
