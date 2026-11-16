# Architecture

```
Browser (Next.js)
   │  POST /api/scans/{mode}  (multipart upload)          GET /api/jobs/{id} (poll)
   ▼
FastAPI (no torch) ── saves upload to DATA_DIR/uploads ──► job queue
   │                                                         │
   │        Celery + Redis (REDIS_URL reachable)  ◄──────────┤
   │        in-process thread (no Redis)          ◄──────────┘
   ▼
Worker: read → de-identify → Stage 1 → Stage 2 → Stage 3 → focus maps → recommendations
        (models loaded once per process by app/ml/registry.py)
```

## Analysis jobs

- `app/jobs/queue.py` chooses the backend once per process: `JOB_BACKEND=auto` uses Celery when
  Redis answers, otherwise `LocalQueue` (one worker thread). Both return the same status
  document: `queued | running | succeeded | failed`, progress, message, result or error.
- The upload file is the hand-off between API and worker (shared volume in Docker). The worker
  deletes it before running the models, so nothing outlives the job.
- Celery settings follow the same pattern as the signature-ai-mlops-platform project:
  `task_acks_late`, `reject_on_worker_lost`, prefetch 1, JSON only, result TTL, time limits.
- User-facing failures (`JobError`) are returned as data, so their message survives the result
  backend; unexpected exceptions are logged with a traceback and reported generically.

## Pipelines

| Step | Single slice | Full series |
| --- | --- | --- |
| Read | pydicom, lumbar/MR checks, plane + sequence → condition | same per slice; junk files ignored |
| Localise | YOLO per condition (box centre) | Stage 1 3D MobileNetV3 (x, y, z) |
| Refine | – | Stage 2 EfficientNetV2-S (x, y) |
| Grade | SeverityNet on a crop from the percentile-windowed slice | same |
| Explain | Grad-CAM on the attention block, tinted by grade | same |

All crops and displayed images come from a 1st–99th percentile window of the raw pixels.
Earlier versions converted 16-bit MR pixels with `Image.fromarray(...).convert("RGB")`, which
saturated roughly half of every slice to white; `tests/test_dicom.py` guards against that.

Checkpoints load with `weights_only=True` and `strict=True`. Stage 1/2 key sets were verified
against the architectures before strict loading was enabled.

## Assistant

- `services/chat/providers.py` streams from Groq (OpenAI-compatible), Gemini (google-genai) and
  Ollama and maps every failure to a kind: rate limit, auth, not found, bad request, timeout,
  unavailable, empty.
- `services/chat/router.py` walks `LLM_FALLBACK_ORDER` × each provider's model list. A failure
  emits a step and moves on; a partial answer is reset before switching. Failed candidates cool
  down (rate limit 60 s or `Retry-After`, auth 10 min, unknown model 1 h) and are tried last.
- `services/chat/store.py` keeps threads and messages in SQLite. Editing a user message replaces
  it and deletes every later message, then answers again (Chainlit behaviour).
- The scan context attached to a thread is reduced to structured findings; pixels never reach a
  language model unless the user attaches an image. Annotated slices, crops and focus maps are
  stored per thread (`chat_assets`) so the app can show them when asked.
- `services/chat/runs.py` runs every answer as a server task. The HTTP stream only follows it:
  closing the page detaches, `GET /threads/{id}/stream` replays and follows, and
  `POST /threads/{id}/stop` ends it (the partial answer is kept as "stopped"). Runs live in the
  API process, so the API runs as one process; scaling out would move them to Redis streams.
- `services/chat/tools.py` holds the app-side tools: `analyze_scan` (an attached DICOM/ZIP goes
  through the normal job queue; progress is streamed with a preview of the scan) and
  `show_images` (level boxes, crops and focus maps for the levels the user names). The app runs
  them, so they work with every model in the fallback chain, including models without tool calls.
- Reasoning is read from Groq `reasoning_format=parsed`, Gemini thought parts, Ollama `thinking`,
  and `<think>` tags; it is stored with the answer and shown only when a model sends it.

## Data stored

| Store | Content | Lifetime |
| --- | --- | --- |
| `DATA_DIR/uploads` | Uploaded file | Deleted when the job starts |
| Redis / in-memory | Job status and result | `JOB_TTL_SECONDS` (1 h) |
| `workspace.sqlite3` | Saved cases, reviews, conversations | Until deleted by the user |

SQLite is not encrypted by the application; protect `DATA_DIR` with host access controls.

## Deployment notes (future work)

The `publish` job pushes `ghcr.io/<owner>/lumber-spine-ai-{api,worker,web}` images on every
green `main` build. A hosted deployment additionally needs TLS, real user authentication
(the reviewer key is a single local secret), a managed Redis, a persistent volume for
`DATA_DIR`, and the model checkpoints mounted at `MODEL_DIR`.
