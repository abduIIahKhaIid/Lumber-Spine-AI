# Lumber Spine AI (SpineScope)

[![CI](https://github.com/abduIIahKhaIid/Lumber-Spine-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/abduIIahKhaIid/Lumber-Spine-AI/actions/workflows/ci.yml)

Web application that grades lumbar spine degeneration on MRI, built on models trained for the
RSNA 2024 Lumbar Spine Degenerative Classification task. It grades three conditions at the five
disc levels (L1/L2 to L5/S1) as **Normal/Mild**, **Moderate** or **Severe**:

| Condition | Sequence | Sides |
| --- | --- | --- |
| Spinal canal stenosis (SCS) | Sagittal T2 / STIR | Central |
| Neural foraminal narrowing (NFN) | Sagittal T1 | Left and right |
| Subarticular stenosis (SS) | Axial T2 | Left and right |

> Research software, not a medical device. Every result must be reviewed by a qualified clinician.

## Features

- **Full-series analysis** (ZIP of one series): Stage 1 3D MobileNetV3 locates each level,
  Stage 2 EfficientNetV2-S refines its position, Stage 3 SeverityNet grades a crop.
- **Single-slice analysis** (one DICOM): YOLO level detection, then the same grading.
- **Evidence view**: interactive spine column, MRI viewer with level boxes colored by grade
  (green / yellow / red), Grad-CAM focus maps tinted by grade, score-profile and grade charts.
- **Recommendations engine**: prioritised, evidence-linked review steps with clinician and
  plain-language wording, from a versioned rule set.
- **Assistant** (Chainlit-style): conversation history with search, rename and delete; edit any
  earlier message and resend; regenerate; stop; image and DICOM attachments; English or Urdu.
  **Automatic LLM fallback**: Groq → Gemini → Ollama (configurable). A rate limit, timeout or
  error switches to the next model without any setting change; a model that sends nothing for
  90 s (`LLM_TIMEOUT_SECONDS`) is replaced by the next one; failing models cool down
  (a missing Ollama model only for a minute, and it is re-checked as soon as it is pulled;
  `curl -X DELETE http://localhost:8000/api/chat/providers/cooldowns` clears all cooldowns).
  Reasoning models show their thinking in a collapsible panel. Attach a DICOM file or series
  ZIP and the SpineScope models analyse it inside the chat (animated progress, result images);
  ask for a level ("show the L4/L5 box") and its slice, focus map and crop are shown. Answers
  keep running on the server if the page is closed, and reopening the chat follows them.
- **Step timings**: every analysis step shows its time live, plus upload, queue and total.
- **Background jobs**: Celery workers with Redis; the API only queues work. Without Redis the API
  falls back to an in-process queue, so local development needs nothing extra.
- **Case library**: save structured findings (never images), review each level, sign off,
  immutable revisions, PDF and FHIR DiagnosticReport export.
- **Privacy**: identifiers are removed from DICOM in memory, uploads are deleted after analysis,
  results expire after an hour unless saved.

## Repository layout

```
backend/                FastAPI + Celery (Python 3.12)
  app/api/routes/       HTTP routes: scans and jobs, assistant, cases, health
  app/core/             settings, security (reviewer key, rate limiting), logging
  app/db/               SQLite schema and connections
  app/jobs/             job queue facade (Celery or in-process) and the job runner
  app/worker/           Celery app and tasks
  app/ml/               architectures, DICOM handling, preprocessing, pipelines, explanations
  app/services/         assistant (providers, fallback router, threads), recommendations, reports
  tests/                pytest suite (includes a real Redis + Celery round trip)
  tools/                offline evaluation and saliency validation
  model/                checkpoints (not in Git)
frontend/               Next.js 15 + React 19 + Tailwind CSS 4
  app/                  routes
  features/scans|chat|cases|home   feature modules
  components/ lib/      shared shell and utilities
docs/                   architecture, operations and AWS deploy guide
deploy/                 production: Caddyfile, deploy script with rollback, EC2 user data, IAM
.github/workflows/ci.yml  one pipeline: lint, tests, build, Docker smoke test, security, publish, deploy
docker-compose.yml      redis + api + worker + web (local)
docker-compose.prod.yml the same behind Caddy (HTTPS) on AWS EC2
```

## Quick start

### Windows (double-click)

1. Install Python 3.12 and Node.js 22 LTS (20.19 or newer works).
2. Run `scripts\setup.bat` once.
3. Copy the checkpoints into `backend\model` (see `backend/model/README.md`).
4. Add at least one of `GROQ_API_KEY`, `GEMINI_API_KEY` or `OLLAMA_BASE_URL` to `backend\.env`.
5. Optional: start Redis (`docker run -d -p 6379:6379 redis:7-alpine`) to use the Celery worker.
6. Double-click `run-project.bat` and open http://localhost:3000.

### Docker Compose (recommended)

Needs only Docker Desktop (Windows/macOS) or Docker Engine with Compose v2 (Linux).

1. Copy the checkpoints into `backend/model`.
2. Copy `backend/.env.example` to `backend/.env` and add your API keys (optional, for the assistant).
3. Start the stack:
   - Windows: double-click `docker-start.bat` (stop with `docker-stop.bat`). It downloads the
     images GitHub CI built; after changing code locally use `docker-rebuild.bat`.
   - Any OS: `docker compose pull` then `docker compose up -d`
     (or `docker compose up -d --build` to build from local code)
4. Open http://localhost:3000. The FastAPI backend is on http://localhost:8000 (docs at `/docs`, health at `/ready`).

| Service | Role |
| --- | --- |
| `redis` | Job broker and result store |
| `api` | FastAPI, queues uploads (no PyTorch) |
| `worker` | Celery + PyTorch, loads the models once and runs analyses |
| `web` | Next.js frontend |

Notes:

- Builds are cached: dependencies (PyTorch, Node packages) sit in their own layers and in
  BuildKit cache mounts, so after the first build a code change rebuilds in seconds. The very
  first local build still downloads CPU PyTorch (10–20 minutes on a slow connection);
  `docker compose pull` avoids it by downloading the images CI already built.
- The CI images live at `ghcr.io/abduiiahkhaiid/lumber-spine-ai-{api,worker,web}`. If
  `docker compose pull` reports "denied", make each package public once on GitHub
  (Profile → Packages → package → Package settings → Change visibility) or run
  `docker login ghcr.io` with a personal access token that has `read:packages`.
- The worker keeps all checkpoints in memory (about 3 GB). On Windows, give Docker Desktop at
  least 6 GB of memory (Settings → Resources, or `.wslconfig` for WSL 2).
- Stop `run-project.bat` windows first; both use ports 3000 and 8000.
- `OLLAMA_BASE_URL=http://localhost:11434` in `backend/.env` is translated to
  `host.docker.internal` inside the containers, so a local Ollama keeps working.
- Saved cases and conversations live in the `app-data` volume and survive restarts.
  `docker compose down -v` deletes them.
- Logs: `docker compose logs -f worker` (analyses) or `docker compose logs -f api`.

### Manual

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[ml,dev]"
cp .env.example .env
uvicorn app.main:app --reload --port 8000
celery -A app.worker.celery_app worker --loglevel=info   # needs Redis; add --pool=solo on Windows

cd ../frontend && npm ci && npm run dev
```

## Checks

```bash
cd backend && ruff check . && ruff format --check . && pytest
cd frontend && npm run check      # prettier, TypeScript, unit tests, production build
```

A single GitHub Actions workflow (`.github/workflows/ci.yml`) runs these, a Docker build and
smoke test of the whole stack, and the security scans: CodeQL, gitleaks, Bandit, pip-audit,
npm audit, Trivy and dependency review. On `main`, images are published to GitHub Container
Registry only when everything passed, and then deployed to AWS EC2 through SSM, with an
automatic rollback if the new version fails its checks. Setup, free HTTPS domain and costs:
[docs/deploy-aws.md](docs/deploy-aws.md). Security scans also re-run weekly. Dependabot opens
pull requests only for security fixes.

## Validation status

No held-out clinical evaluation is included yet. `backend/tools/evaluate.py` computes accuracy,
balanced accuracy, macro-F1, per-class recall, the RSNA weighted log loss, calibration error and a
temperature for calibration from labelled predictions. Calibrated scores are only shown after an
evaluation artifact is approved for the exact checkpoint.
