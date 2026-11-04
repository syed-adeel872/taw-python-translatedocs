"""Production-path PDF overlay tests with synthetic documents.

These tests exercise ``PdfProcessor.process`` without any live provider. They
verify redaction, background preservation, contrast selection, source-text
removal, strict overflow failure and cleanup of partial output.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
import pytest

from app.config import Settings
from app.errors import DocumentProcessingError
from app.services.documents.pdf_processor import PdfProcessor
from app.services.translation.base import TranslationProvider, TranslationService


class FixedProvider(TranslationProvider):
    name = "fixed"

    def __init__(self, translated: str = "Bonjour") -> None:
        self.translated = translated

    def translate(self, texts, source_language, target_language):
        return [self.translated for _ in texts]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite:///:memory:",
        storage_root=tmp_path,
        ai_provider="mock",
        pdf_font_path="",
    )


def _processor(provider: TranslationProvider, tmp_path: Path) -> PdfProcessor:
    return PdfProcessor(
        TranslationService(provider, max_retries=0, retry_backoff=0),
        _settings(tmp_path),
    )


def _write_pdf(document: fitz.Document, tmp_path: Path) -> Path:
    path = tmp_path / "source.pdf"
    path.write_bytes(document.tobytes(garbage=3, deflate=True))
    return path


def _process(
    document: fitz.Document,
    provider: TranslationProvider,
    tmp_path: Path,
) -> tuple[Path, Path]:
    source_path = _write_pdf(document, tmp_path)
    output_path = tmp_path / "translated.pdf"
    _processor(provider, tmp_path).process(
        source_path, output_path, "auto", "fr"
    )
    return source_path, output_path


def _page_text(path: Path) -> str:
    document = fitz.open(str(path))
    try:
        return "\n".join(page.get_text() for page in document)
    finally:
        document.close()


def test_process_removes_source_text_and_preserves_solid_background(tmp_path):
    document = fitz.open()
    page = document.new_page(width=400, height=500)
    page.draw_rect(
        fitz.Rect(20, 40, 330, 100),
        color=None,
        fill=(1.0, 1.0, 0.85),
    )
    page.insert_text(
        (36, 72), "Hello export invoice", fontsize=12, fontname="helv"
    )
    try:
        _source, output = _process(document, FixedProvider("Bonjour"), tmp_path)
    finally:
        document.close()

    text = _page_text(output)
    assert "Bonjour" in text
    assert "Hello export invoice" not in text

    reopened = fitz.open(str(output))
    try:
        drawing_fills = [
            drawing["fill"]
            for drawing in reopened[0].get_drawings()
            if drawing.get("fill") is not None
        ]
        assert any(
            all(abs(actual - expected) < 0.01 for actual, expected in zip(fill, (1.0, 1.0, 0.85)))
            for fill in drawing_fills
        )
    finally:
        reopened.close()


def test_process_chooses_white_text_on_dark_background(tmp_path):
    document = fitz.open()
    page = document.new_page(width=400, height=500)
    page.draw_rect(
        fitz.Rect(20, 40, 330, 100),
        color=None,
        fill=(0.02, 0.02, 0.02),
    )
    page.insert_text(
        (36, 72),
        "Hello export invoice",
        fontsize=12,
        fontname="helv",
        color=(0.0, 0.0, 0.0),
    )
    try:
        _source, output = _process(document, FixedProvider("Bonjour"), tmp_path)
    finally:
        document.close()

    reopened = fitz.open(str(output))
    try:
        spans = [
            span
            for block in reopened[0].get_text("dict")["blocks"]
            for line in block.get("lines", [])
            for span in line.get("spans", [])
            if "Bonjour" in span.get("text", "")
        ]
        assert spans
        assert any(span["color"] == 0xFFFFFF for span in spans), spans
    finally:
        reopened.close()


def test_process_preserves_blank_pages(tmp_path):
    document = fitz.open()
    first = document.new_page(width=400, height=500)
    first.insert_text((36, 72), "Hello export invoice", fontsize=12, fontname="helv")
    document.new_page(width=300, height=600)
    try:
        _source, output = _process(document, FixedProvider("Bonjour"), tmp_path)
    finally:
        document.close()

    reopened = fitz.open(str(output))
    try:
        assert reopened.page_count == 2
        assert "Bonjour" in reopened[0].get_text()
        assert reopened[1].get_text().strip() == ""
        assert (round(reopened[1].rect.width, 1), round(reopened[1].rect.height, 1)) == (
            300.0,
            600.0,
        )
    finally:
        reopened.close()


def test_process_rejects_text_over_raster_image_without_partial_output(tmp_path):
    document = fitz.open()
    page = document.new_page(width=400, height=500)
    samples = bytes([200, 30, 30] * (20 * 20))
    pix = fitz.Pixmap(fitz.csRGB, 20, 20, samples, 0)
    page.insert_image(fitz.Rect(20, 40, 140, 100), stream=pix.tobytes("png"))
    page.insert_text(
        (36, 72), "Hello export invoice", fontsize=12, fontname="helv"
    )
    source = _write_pdf(document, tmp_path)
    original_bytes = source.read_bytes()
    output = tmp_path / "translated.pdf"
    try:
        with pytest.raises(DocumentProcessingError, match="image"):
            _processor(FixedProvider("Bonjour"), tmp_path).process(
                source, output, "auto", "fr"
            )
    finally:
        document.close()
        pix = None

    assert not output.is_file()
    assert source.read_bytes() == original_bytes


def test_process_rejects_overflow_without_partial_output(tmp_path):
    document = fitz.open()
    page = document.new_page(width=400, height=500)
    page.insert_text((36, 72), "Hi", fontsize=12, fontname="helv")
    source = _write_pdf(document, tmp_path)
    original_bytes = source.read_bytes()
    output = tmp_path / "translated.pdf"
    try:
        with pytest.raises(DocumentProcessingError, match="does not fit"):
            _processor(
                FixedProvider(
                    "This translation is deliberately much too long for the box"
                ),
                tmp_path,
            ).process(source, output, "auto", "fr")
    finally:
        document.close()

    assert not output.is_file()
    assert source.read_bytes() == original_bytes


def test_process_rejects_partial_vector_background(tmp_path):
    document = fitz.open()
    page = document.new_page(width=400, height=500)
    page.draw_rect(
        fitz.Rect(20, 40, 70, 100),
        color=None,
        fill=(0.9, 0.8, 0.2),
    )
    page.insert_text(
        (36, 72), "Hello export invoice", fontsize=12, fontname="helv"
    )
    source = _write_pdf(document, tmp_path)
    output = tmp_path / "translated.pdf"
    try:
        with pytest.raises(DocumentProcessingError, match="background"):
            _processor(FixedProvider("Bonjour"), tmp_path).process(
                source, output, "auto", "fr"
            )
    finally:
        document.close()

    assert not output.is_file()
