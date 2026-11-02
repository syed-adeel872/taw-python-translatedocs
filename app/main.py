"""FastAPI application factory and ASGI entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router
from app.config import Settings, get_settings
from app.database import Database
from app.errors import AppError
from app.services.jobs import JobRunner
from app.services.translation.base import TranslationService
from app.services.translation.factory import UnavailableProvider, build_translation_provider
from app.storage import Storage

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
TEMPLATE_DIR = APP_DIR / "templates"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_directories()

    storage = Storage(settings.storage_path)
    storage.ensure()
    database = Database(settings.database_url, echo=settings.database_echo)

    try:
        provider = build_translation_provider(settings)
    except AppError as exc:
        provider = UnavailableProvider("unconfigured", exc.user_message)
    except Exception:
        logger.exception("Could not initialise the translation provider")
        provider = UnavailableProvider(
            "unconfigured",
            "The translation provider could not be initialised. Check the server logs.",
        )

    translator = TranslationService(
        provider,
        batch_size=settings.ai_batch_size,
        max_retries=settings.ai_max_retries,
        max_document_chars=settings.max_document_chars,
    )
    runner = JobRunner(database, storage, translator, settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.ensure_directories()
        storage.ensure()
        try:
            database.require_current_schema()
            logger.info(
                "TranslateDocs started (provider=%s, database=%s)",
                provider.name,
                _database_label(settings.database_url),
            )
            yield
        finally:
            database.dispose()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Translate DOCX and PDF export documents while preserving structure.",
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.database = database
    app.state.storage = storage
    app.state.translator = translator
    app.state.runner = runner
    app.state.templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; "
            "frame-ancestors 'none'"
        )
        if request.url.path.startswith(("/jobs", "/api/jobs")):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(router)
    return app


def _database_label(url: str) -> str:
    if url.startswith("sqlite"):
        return "sqlite (development only)"
    if url.startswith("postgresql"):
        return "postgresql"
    return "configured database"


app = create_app()
