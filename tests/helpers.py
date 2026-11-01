from __future__ import annotations

import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from alembic import command
from alembic.config import Config
from docx import Document

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_migrations(database_url: str) -> None:
    _validate_migration_target(database_url)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")


def _validate_migration_target(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError(
            "Refusing to run migrations: tests may only target isolated SQLite "
            "databases under the system temporary directory."
        )

    database_path = database_url.removeprefix(prefix)
    if not database_path or any(char in database_path for char in "?#"):
        raise ValueError(
            "Refusing to run migrations: the SQLite target must be a plain file "
            "path under the system temporary directory."
        )

    path = Path(database_path)
    if not path.is_absolute():
        raise ValueError(
            "Refusing to run migrations: the SQLite target must be an absolute "
            "path under the system temporary directory."
        )

    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        path.resolve().relative_to(temp_root)
    except ValueError:
        raise ValueError(
            "Refusing to run migrations: the SQLite target is outside the "
            "system temporary directory."
        ) from None


def make_docx_bytes(
    *,
    heading: str = "Export summary",
    bold_text: str = "Bold product name",
    italic_text: str = "italic note",
    table_text: str = "Quantity 120 cartons",
    header_text: str = "Trading company header",
) -> bytes:
    document = Document()
    document.add_heading(heading, level=1)

    paragraph = document.add_paragraph()
    bold_run = paragraph.add_run(bold_text)
    bold_run.bold = True
    paragraph.add_run(" and ")
    italic_run = paragraph.add_run(italic_text)
    italic_run.italic = True

    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Description"
    table.cell(0, 1).text = table_text

    document.sections[0].header.paragraphs[0].text = header_text

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_empty_docx_bytes() -> bytes:
    document = Document()
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_invalid_docx_zip() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<not-a-valid-document")
    return buffer.getvalue()


def make_pdf_bytes(
    pages: list[tuple[float, float, str]] | None = None,
    *,
    password: str | None = None,
) -> bytes:
    page_specs = pages or [
        (400.0, 500.0, "Hello export invoice 120 cartons"),
        (300.0, 600.0, "Second page terms and conditions"),
    ]
    document = fitz.open()
    try:
        for width, height, text in page_specs:
            page = document.new_page(width=width, height=height)
            if text:
                page.insert_text((36, 60), text, fontsize=12)
        if password:
            return document.tobytes(
                encryption=fitz.PDF_ENCRYPT_AES_256,
                owner_pw="owner-secret",
                user_pw=password,
            )
        return document.tobytes()
    finally:
        document.close()


def make_blank_pdf_bytes() -> bytes:
    document = fitz.open()
    try:
        document.new_page(width=400, height=500)
        return document.tobytes()
    finally:
        document.close()


def upload(
    client,
    data: bytes,
    *,
    filename: str = "sample.docx",
    target: str = "es",
    source: str = "auto",
):
    return client.post(
        "/translate",
        files={"file": (filename, data, "application/octet-stream")},
        data={"target_language": target, "source_language": source},
        follow_redirects=False,
    )
