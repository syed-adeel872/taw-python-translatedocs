"""Background job execution and persistence."""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import Settings
from app.database import Database
from app.errors import AppError, DocumentProcessingError
from app.models import Job, JobStatus, utcnow
from app.services.documents.docx_processor import DocxProcessor
from app.services.documents.pdf_processor import PdfProcessor
from app.services.documents.validation import sanitize_filename
from app.services.translation.base import TranslationService
from app.storage import Storage

logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(
        self,
        database: Database,
        storage: Storage,
        translator: TranslationService,
        settings: Settings,
    ) -> None:
        self.database = database
        self.storage = storage
        self.translator = translator
        self.settings = settings

    @property
    def provider_name(self) -> str:
        return self.translator.provider_name

    def run(self, job_id: str) -> None:
        with self.database.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                logger.warning("Job %s disappeared before processing", job_id)
                return
            if job.status != JobStatus.QUEUED:
                logger.info("Job %s already handled (status=%s)", job_id, job.status)
                return

            job.status = JobStatus.PROCESSING
            job.started_at = utcnow()
            job.updated_at = utcnow()
            session.commit()

            input_path: Path | None = None
            output_path: Path | None = None
            succeeded = False

            try:
                if not job.input_path:
                    raise DocumentProcessingError("The uploaded file could not be found.")
                input_path = self.storage.upload_path(job.input_path)
                if not input_path.is_file():
                    raise DocumentProcessingError(
                        "The uploaded file is no longer available. Please upload it again."
                    )

                extension = ".docx" if job.file_type == "docx" else ".pdf"
                output_path, storage_name = self.storage.new_output(extension)

                if job.file_type == "docx":
                    processor = DocxProcessor(self.translator)
                elif job.file_type == "pdf":
                    processor = PdfProcessor(self.translator, self.settings)
                else:
                    raise DocumentProcessingError("Unsupported stored file type.")

                result = processor.process(
                    input_path,
                    output_path,
                    job.source_language,
                    job.target_language,
                )

                job.status = JobStatus.COMPLETED
                job.output_path = storage_name
                job.output_filename = _output_filename(
                    job.original_filename, job.target_language, extension
                )
                job.characters_translated = result.characters
                job.segments_translated = result.segments
                job.warnings = "\n".join(result.warnings)
                job.error_message = None
                job.completed_at = utcnow()
                succeeded = True
            except AppError as exc:
                job.status = JobStatus.FAILED
                job.error_message = exc.user_message
                logger.info("Job %s failed: %s", job_id, type(exc).__name__)
            except Exception:
                job.status = JobStatus.FAILED
                job.error_message = (
                    "An unexpected error occurred while processing the document."
                )
                logger.exception("Unexpected failure while processing job %s", job_id)
            finally:
                if input_path is not None:
                    try:
                        input_path.unlink(missing_ok=True)
                    except OSError:
                        logger.warning("Could not remove input file for job %s", job_id)

                if not succeeded and output_path is not None:
                    try:
                        output_path.unlink(missing_ok=True)
                    except OSError:
                        logger.warning("Could not remove partial output for job %s", job_id)

                job.updated_at = utcnow()
                try:
                    session.commit()
                except Exception:
                    session.rollback()
                    logger.exception("Could not persist final status for job %s", job_id)


def _output_filename(original_filename: str, target_language: str, extension: str) -> str:
    stem = Path(original_filename).stem or "document"
    stem = sanitize_filename(stem)[:80]
    return sanitize_filename(f"{stem}-{target_language}{extension}")
