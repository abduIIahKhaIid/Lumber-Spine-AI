#!/usr/bin/env bash
# Local development on macOS/Linux: API + Celery worker (if Redis is up) + web.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
if python -c "import redis,sys; sys.exit(0 if redis.Redis(socket_connect_timeout=1).ping() else 1)" 2>/dev/null; then
  celery -A app.worker.celery_app worker --loglevel=info --concurrency=1 &
fi
uvicorn app.main:app --reload --port 8000 &
cd "$ROOT/frontend" && npm run dev
