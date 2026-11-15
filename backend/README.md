# Backend

FastAPI API plus Celery workers for lumbar MRI grading. See the repository README for setup.

- Entry point: `uvicorn app.main:app`
- Worker: `celery -A app.worker.celery_app worker --loglevel=info` (`--pool=solo` on Windows)
- Settings: `.env` (template in `.env.example`)
- Tests: `pytest` (set `REDIS_URL` to also run the Celery round-trip test)

## API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/scans/{single\|multi}` | Upload a DICOM or series ZIP, returns `job_id` (202) |
| GET | `/api/jobs/{id}` | Job state, progress, result |
| GET | `/api/jobs/{id}/report.pdf` | PDF report of a finished analysis |
| POST | `/api/convert-dicom` | DICOM to JPEG preview (assistant attachments) |
| GET/POST | `/api/chat/threads` | List or create conversations |
| GET/PATCH/DELETE | `/api/chat/threads/{id}` | Read, rename or delete a conversation |
| POST | `/api/chat/threads/{id}/messages` | Send a message, streamed as server-sent events |
| POST | `/api/chat/threads/{id}/messages/{mid}/edit` | Edit a message and answer again |
| POST | `/api/chat/threads/{id}/regenerate` | Answer the last question again |
| GET | `/api/chat/providers` | Fallback chain and cooldowns |
| * | `/api/cases/...` | Case library (requires `X-Review-Key`) |
| GET | `/health`, `/ready` | Liveness and readiness (queue, worker, models) |

Interactive documentation: http://localhost:8000/api/docs
