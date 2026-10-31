"""Upload validation: extension, size, magic bytes and real file structure."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pymupdf as fitz

from app.errors import (
    CorruptedDocumentError,
    FileTooLargeError,
    InvalidUploadError,
    PasswordProtectedError,
    UnsupportedFileTypeError,
)

ALLOWED_EXTENSIONS = {".docx": "docx", ".pdf": "pdf"}
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class ValidatedUpload:
    file_type: str
    extension: str
    filename: str
    size: int


def sanitize_filename(raw_name: str) -> str:
    name = (raw_name or "").replace("\\", "/").split("/")[-1]
    name = _CONTROL_CHARS.sub("", name).strip()
    if not name or name in {".", ".."}:
        return "document"
    if len(name) > 180:
        stem = Path(name).stem[:160]
        suffix = Path(name).suffix[:10]
        name = f"{stem}{suffix}"
    return name


def validate_upload(raw_name: str | None, data: bytes, max_bytes: int) -> ValidatedUpload:
    if not raw_name:
        raise InvalidUploadError("Please choose a DOCX or PDF file to upload.")

    filename = sanitize_filename(raw_name)
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError()

    if not data:
        raise InvalidUploadError("The uploaded file is empty.")

    if len(data) > max_bytes:
        limit_mb = max(1, max_bytes // (1024 * 1024))
        raise FileTooLargeError(f"The uploaded file is larger than the {limit_mb} MB limit.")

    file_type = ALLOWED_EXTENSIONS[extension]
    if file_type == "docx":
        _validate_docx(data)
    else:
        _validate_pdf(data)

    return ValidatedUpload(
        file_type=file_type,
        extension=extension,
        filename=filename,
        size=len(data),
    )


def _validate_docx(data: bytes) -> None:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
            if archive.testzip() is not None:
                raise CorruptedDocumentError()
    except zipfile.BadZipFile as exc:
        raise CorruptedDocumentError(
            "The DOCX file is corrupted or is not a real Word document."
        ) from exc

    if "[Content_Types].xml" not in names or "word/document.xml" not in names:
        raise InvalidUploadError(
            "The file does not look like a Word document. Upload a .docx file."
        )


def _validate_pdf(data: bytes) -> None:
    if b"%PDF-" not in data[:1024]:
        raise CorruptedDocumentError(
            "The PDF file is corrupted or is not a real PDF document."
        )

    document = None
    try:
        document = fitz.open(stream=data, filetype="pdf")
        if document.needs_pass:
            raise PasswordProtectedError()
        if document.page_count == 0:
            raise CorruptedDocumentError("The PDF contains no pages.")
    except PasswordProtectedError:
        raise
    except Exception as exc:  # PyMuPDF raises several internal exception types
        raise CorruptedDocumentError(
            "The PDF file is corrupted or cannot be opened."
        ) from exc
    finally:
        if document is not None:
            document.close()
