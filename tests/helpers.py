from __future__ import annotations

import zipfile
from io import BytesIO

import pymupdf as fitz
from docx import Document


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
