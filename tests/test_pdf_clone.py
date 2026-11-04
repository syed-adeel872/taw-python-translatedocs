"""Focused tests for the PDF document cloning helper.

These tests exercise ``_clone_document`` directly with synthetic PDFs built
in memory, so they verify cloning behaviour without any live provider call or
filesystem dependency.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pymupdf as fitz

from app.services.documents.pdf_processor import _clone_document


def _build_document(text: str = "Hello overlay world", pages: int = 1) -> fitz.Document:
    document = fitz.open()
    for _ in range(pages):
        page = document.new_page(width=400, height=500)
        page.insert_text((36, 72), text, fontsize=12, fontname="helv")
    return document


def test_clone_has_same_page_count():
    document = _build_document(pages=2)
    try:
        clone = _clone_document(document)
        try:
            assert clone.page_count == document.page_count == 2
        finally:
            clone.close()
    finally:
        document.close()


def test_clone_preserves_extracted_text():
    document = _build_document("Hello overlay world")
    try:
        clone = _clone_document(document)
        try:
            assert "Hello overlay world" in clone[0].get_text()
        finally:
            clone.close()
    finally:
        document.close()


def test_closing_original_does_not_affect_clone():
    document = _build_document("Independent copy")
    clone = _clone_document(document)
    document.close()
    try:
        assert clone.page_count == 1
        assert "Independent copy" in clone[0].get_text()
    finally:
        clone.close()


def test_clone_can_be_saved_and_reopened():
    document = _build_document("Persisted clone")
    clone = _clone_document(document)
    document.close()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "clone.pdf"
            clone.save(str(path), garbage=3, deflate=True)
            reopened = fitz.open(str(path))
            try:
                assert reopened.page_count == 1
                assert "Persisted clone" in reopened[0].get_text()
            finally:
                reopened.close()
    finally:
        clone.close()


def test_original_remains_usable_until_explicitly_closed():
    document = _build_document("Still usable")
    clone = _clone_document(document)
    try:
        # Original is still open and queryable after cloning.
        assert document.page_count == 1
        assert "Still usable" in document[0].get_text()
        assert clone.page_count == 1
    finally:
        clone.close()
        document.close()
