"""Upload validation: extension, size, magic bytes and real file structure."""

from __future__ import annotations

import re
import zipfile
import zlib
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


# Safe limits for DOCX (ZIP) uploads. These are checked from ZIP metadata only;
# the archive is never fully extracted during validation.
# Safe limits for DOCX (ZIP) uploads. Declared ZIP metadata is not trusted on its
# own; entries are also read in bounded chunks and their actual decompressed size
# is counted. The archive is never fully extracted into memory.
MAX_DOCX_ENTRIES = 1000
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024  # 50 MB total
MAX_DOCX_ENTRY_UNCOMPRESSED_BYTES = 25 * 1024 * 1024  # 25 MB per entry
MAX_DOCX_COMPRESSION_RATIO = 200
MIN_DOCX_COMPRESSED_BYTES_FOR_RATIO_CHECK = 1024
_DOCX_CHUNK_SIZE = 64 * 1024


def _validate_docx(data: bytes) -> None:
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except (zipfile.BadZipFile, OSError, EOFError, RuntimeError) as exc:
        raise CorruptedDocumentError(
            "The DOCX file is corrupted or is not a real Word document."
        ) from exc

    try:
        infos = archive.infolist()
    except (OSError, RuntimeError, zipfile.LargeZipFile) as exc:
        archive.close()
        raise CorruptedDocumentError(
            "The DOCX file is corrupted or is not a real Word document."
        ) from exc

    if len(infos) > MAX_DOCX_ENTRIES:
        archive.close()
        raise InvalidUploadError(
            "The DOCX file contains too many parts and cannot be processed."
        )

    names = {info.filename for info in infos}
    if "[Content_Types].xml" not in names or "word/document.xml" not in names:
        archive.close()
        raise InvalidUploadError(
            "The file does not look like a Word document. Upload a .docx file."
        )

    total_uncompressed = 0
    for info in infos:
        if info.flag_bits & 0x1:
            archive.close()
            raise InvalidUploadError(
                "Encrypted DOCX files are not supported."
            )

        if info.file_size > MAX_DOCX_ENTRY_UNCOMPRESSED_BYTES:
            archive.close()
            raise InvalidUploadError(
                "The DOCX file contains an oversized part and cannot be processed."
            )

        total_uncompressed += info.file_size
        if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
            archive.close()
            raise InvalidUploadError(
                "The DOCX file is too large when decompressed and cannot be "
                "processed."
            )

    for info in infos:
        if (
            info.compress_size >= MIN_DOCX_COMPRESSED_BYTES_FOR_RATIO_CHECK
            and info.file_size > 0
        ):
            ratio = info.file_size / max(1, info.compress_size)
            if ratio > MAX_DOCX_COMPRESSION_RATIO:
                archive.close()
                raise InvalidUploadError(
                    "The DOCX file has a suspicious compression ratio and cannot "
                    "be processed."
                )

    # Count actual decompressed bytes by reading each entry in bounded chunks.
    actual_total = 0
    for info in infos:
        if info.is_dir():
            continue
        try:
            with archive.open(info, "r") as member:
                entry_bytes = 0
                while True:
                    chunk = member.read(_DOCX_CHUNK_SIZE)
                    if not chunk:
                        break
                    entry_bytes += len(chunk)
                    actual_total += len(chunk)
                    if entry_bytes > MAX_DOCX_ENTRY_UNCOMPRESSED_BYTES:
                        raise InvalidUploadError(
                            "The DOCX file contains an oversized part and cannot "
                            "be processed."
                        )
                    if actual_total > MAX_DOCX_UNCOMPRESSED_BYTES:
                        raise InvalidUploadError(
                            "The DOCX file is too large when decompressed and "
                            "cannot be processed."
                        )
        except (OSError, RuntimeError, EOFError, zipfile.BadZipFile, zlib.error) as exc:
            archive.close()
            raise CorruptedDocumentError(
                "The DOCX file is corrupted or is not a real Word document."
            ) from exc
        except InvalidUploadError:
            archive.close()
            raise

    # archive.open() above already decompressed each entry and validated its CRC,
    # so no additional unbounded testzip() pass is required.

    archive.close()


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
