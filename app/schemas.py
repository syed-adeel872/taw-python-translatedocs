"""Pydantic response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models import Job, JobStatus


class JobStatusResponse(BaseModel):
    id: str
    status: str
    original_filename: str
    file_type: str
    source_language: str
    target_language: str
    provider: str
    error_message: str | None = None
    warnings: list[str] = []
    characters_translated: int = 0
    segments_translated: int = 0
    download_url: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    @classmethod
    def from_job(cls, job: Job) -> "JobStatusResponse":
        warnings = [line for line in (job.warnings or "").splitlines() if line.strip()]
        download_url = None
        if job.status == JobStatus.COMPLETED and job.output_path:
            download_url = f"/jobs/{job.id}/download"
        return cls(
            id=job.id,
            status=job.status,
            original_filename=job.original_filename,
            file_type=job.file_type,
            source_language=job.source_language,
            target_language=job.target_language,
            provider=job.provider,
            error_message=job.error_message,
            warnings=warnings,
            characters_translated=job.characters_translated,
            segments_translated=job.segments_translated,
            download_url=download_url,
            created_at=job.created_at,
            completed_at=job.completed_at,
        )
