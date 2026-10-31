"""HTTP routes: upload, status, download and health."""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import text

from app.config import Settings
from app.errors import AppError, FileTooLargeError
from app.languages import LANGUAGES, TARGET_LANGUAGES, is_valid_source, is_valid_target
from app.models import Job, JobStatus, utcnow
from app.schemas import JobStatusResponse
from app.services.documents.validation import validate_upload

logger = logging.getLogger(__name__)

router = APIRouter()

_STATUS_LABELS = {
    JobStatus.QUEUED: "Queued",
    JobStatus.PROCESSING: "Translating",
    JobStatus.COMPLETED: "Completed",
    JobStatus.FAILED: "Failed",
}


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return _render_index(request)


@router.post("/translate")
async def create_translation(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    target_language: str = Form(...),
    source_language: str = Form("auto"),
) -> HTMLResponse:
    settings: Settings = request.app.state.settings
    target = (target_language or "").strip()
    source = (source_language or "auto").strip()
    prefill = {"target_language": target, "source_language": source}

    if not is_valid_target(target):
        return _render_index(
            request,
            error="Choose a supported target language.",
            status_code=400,
            prefill=prefill,
        )
    if not is_valid_source(source):
        return _render_index(
            request,
            error="Choose a valid source language, or use auto-detect.",
            status_code=400,
            prefill=prefill,
        )

    try:
        data = await _read_limited(file, settings.max_upload_bytes)
        validated = validate_upload(file.filename, data, settings.max_upload_bytes)

        storage = request.app.state.storage
        input_path, storage_name = storage.save_upload(data, validated.extension)

        job = Job(
            id=uuid4().hex,
            original_filename=validated.filename,
            file_type=validated.file_type,
            source_language=source,
            target_language=target,
            provider=request.app.state.runner.provider_name,
            status=JobStatus.QUEUED,
            input_path=storage_name,
            created_at=utcnow(),
            updated_at=utcnow(),
        )

        with request.app.state.database.session() as session:
            session.add(job)
            session.commit()

        background_tasks.add_task(request.app.state.runner.run, job.id)
        return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)

    except AppError as exc:
        return _render_index(
            request,
            error=exc.user_message,
            status_code=exc.status_code,
            prefill=prefill,
        )
    except Exception:
        logger.exception("Upload failed unexpectedly")
        return _render_index(
            request,
            error="The document could not be accepted. Please try again.",
            status_code=500,
            prefill=prefill,
        )
    finally:
        await file.close()


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str) -> HTMLResponse:
    job = _get_job(request, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Translation job not found.")

    warnings = [line for line in (job.warnings or "").splitlines() if line.strip()]
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="job.html",
        context={
            "app_name": request.app.state.settings.app_name,
            "job": job,
            "status_label": _STATUS_LABELS.get(job.status, job.status),
            "warnings": warnings,
            "target_languages": TARGET_LANGUAGES,
        },
    )


@router.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def job_status(request: Request, job_id: str) -> JobStatusResponse:
    job = _get_job(request, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Translation job not found.")
    return JobStatusResponse.from_job(job)


@router.get("/jobs/{job_id}/download")
def download(request: Request, job_id: str) -> FileResponse:
    job = _get_job(request, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Translation job not found.")
    if job.status == JobStatus.FAILED:
        raise HTTPException(
            status_code=409,
            detail=job.error_message or "This translation did not complete.",
        )
    if job.status != JobStatus.COMPLETED or not job.output_path:
        raise HTTPException(
            status_code=409, detail="The translation is still in progress."
        )

    try:
        path = request.app.state.storage.output_path(job.output_path)
    except AppError:
        raise HTTPException(
            status_code=404, detail="The translated file is no longer available."
        ) from None

    if not path.is_file():
        raise HTTPException(
            status_code=404, detail="The translated file is no longer available."
        )

    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if job.file_type == "docx"
        else "application/pdf"
    )
    return FileResponse(
        path,
        media_type=media_type,
        filename=job.output_filename or f"translated-{job.id}.{job.file_type}",
    )


@router.get("/health")
def health(request: Request) -> JSONResponse:
    try:
        with request.app.state.database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Health check could not reach the database")
        return JSONResponse(
            {"status": "degraded", "database": "unavailable", "provider": request.app.state.runner.provider_name},
            status_code=503,
        )
    return JSONResponse(
        {
            "status": "ok",
            "database": "ok",
            "provider": request.app.state.runner.provider_name,
        }
    )


async def _read_limited(file: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            limit_mb = max(1, max_bytes // (1024 * 1024))
            raise FileTooLargeError(
                f"The uploaded file is larger than the {limit_mb} MB limit."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _get_job(request: Request, job_id: str) -> Job | None:
    with request.app.state.database.session() as session:
        return session.get(Job, job_id)


def _render_index(
    request: Request,
    *,
    error: str | None = None,
    status_code: int = 200,
    prefill: dict[str, str] | None = None,
) -> HTMLResponse:
    settings: Settings = request.app.state.settings
    provider_name = request.app.state.runner.provider_name
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": settings.app_name,
            "languages": TARGET_LANGUAGES,
            "all_languages": LANGUAGES,
            "provider_name": provider_name,
            "is_mock": provider_name == "mock",
            "max_upload_mb": settings.max_upload_mb,
            "error": error,
            "prefill": prefill or {},
        },
        status_code=status_code,
    )
