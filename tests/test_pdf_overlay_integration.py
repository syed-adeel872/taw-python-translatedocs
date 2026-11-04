"""Integration test for the PDF overlay pipeline.

Exercises ``_overlay_pdf`` end to end with a synthetic one-page PDF: the page
is cloned, a translated block is overlaid onto the clone, the result is saved
and reopened, and the rendered text is checked with the strict validation
helpers. No live provider call, no filesystem fixture, no wiring of
``process()``.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from app.services.documents.pdf_processor import (
    _clone_document,
    _extract_pages,
    _overlay_pdf,
)


def _build_source_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=400, height=500)
    page.insert_text((36, 72), "Hello world", fontsize=12, fontname="helv")
    document.save(str(path), garbage=3, deflate=True)
    document.close()


def test_overlay_pdf_renders_translated_text(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "overlay.pdf"
    _build_source_pdf(source)

    document = fitz.open(str(source))
    try:
        pages = _extract_pages(document)
        clone = _clone_document(document)
    finally:
        document.close()

    try:
        assert len(pages) == 1
        assert len(pages[0].blocks) == 1
        translations = ["Bonjour"]

        _overlay_pdf(clone, pages, translations, output, font_path=None, rtl=False)

        assert output.is_file()
        reopened = fitz.open(str(output))
        try:
            assert reopened.page_count == 1
            block = pages[0].blocks[0]
            rect = fitz.Rect()
            for span in block.spans:
                rect |= span.rect
            rendered = " ".join(
                word[4] for word in reopened[0].get_text("words", clip=rect)
            )
            assert "Bonjour" in rendered
            assert "Hello" not in rendered
        finally:
            reopened.close()
    finally:
        clone.close()
