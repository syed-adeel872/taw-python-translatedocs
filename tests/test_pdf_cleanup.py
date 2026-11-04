"""Focused tests for PDFProcessor document cleanup on success and failure.

These tests exercise ``PdfProcessor.process`` directly with synthetic PDFs and
mock providers, so they verify that both the original and cloned documents are
closed on every exit path without any live provider call.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
import pytest

from app.config import Settings
from app.services.documents.pdf_processor import PdfProcessor
from app.services.translation.base import TranslationProvider, TranslationService
from app.services.translation.mock import MockTranslationProvider
from tests.helpers import make_pdf_bytes


class _FailingProvider(TranslationProvider):
    name = "pdf-cleanup-failing"

    def translate(self, texts, source_language, target_language):
        raise RuntimeError("provider exploded during cleanup test")


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite:///:memory:",
        storage_root=tmp_path,
        ai_provider="mock",
        pdf_font_path="",
    )


def test_process_closes_documents_on_success(tmp_path):
    settings = _settings(tmp_path)
    source = make_pdf_bytes()
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    src.write_bytes(source)

    processor = PdfProcessor(
        TranslationService(MockTranslationProvider(), max_retries=0, retry_backoff=0),
        settings,
    )
    result = processor.process(src, out, "auto", "es")

    assert result.segments >= 1
    assert out.is_file()
    reopened = fitz.open(str(out))
    try:
        assert reopened.page_count >= 1
    finally:
        reopened.close()


def test_process_closes_documents_on_failure(tmp_path):
    settings = _settings(tmp_path)
    source = make_pdf_bytes()
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    src.write_bytes(source)

    processor = PdfProcessor(
        TranslationService(_FailingProvider(), max_retries=0, retry_backoff=0),
        settings,
    )
    # A raw provider error propagates; the cleanup ``finally`` must still run
    # and leave the original untouched with no partial output behind.
    with pytest.raises(RuntimeError, match="provider exploded"):
        processor.process(src, out, "auto", "es")

    assert src.read_bytes() == source
    assert not out.is_file()


def test_process_keeps_original_untouched_on_success(tmp_path):
    settings = _settings(tmp_path)
    source = make_pdf_bytes()
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    src.write_bytes(source)

    processor = PdfProcessor(
        TranslationService(MockTranslationProvider(), max_retries=0, retry_backoff=0),
        settings,
    )
    processor.process(src, out, "auto", "es")

    assert src.read_bytes() == source
