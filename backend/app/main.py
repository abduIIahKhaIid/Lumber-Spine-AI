"""FastAPI application entry point: `uvicorn app.main:app`."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import cases, chat, health, scans
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.database import connect
from app.jobs.queue import get_queue


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    with connect():  # create the SQLite schema up front
        pass
    get_queue()  # decide Celery vs in-process once, and log it
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Review-Key"],
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    for module in (health, scans, chat, cases):
        app.include_router(module.router)
    return app


app = create_app()
