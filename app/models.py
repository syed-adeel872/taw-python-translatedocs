"""Database models. Only job metadata is stored, never document contents."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

    ALL = {QUEUED, PROCESSING, COMPLETED, FAILED}
    TERMINAL = {COMPLETED, FAILED}


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    source_language: Mapped[str] = mapped_column(String(20), nullable=False)
    target_language: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=JobStatus.QUEUED, index=True
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    characters_translated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    segments_translated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
