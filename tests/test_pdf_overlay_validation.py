"""Focused tests for PDF overlay text validation helpers.

These tests exercise ``_normalize_text``, ``_validate_block`` and
``_extract_block_text`` directly, so they verify validation behaviour without
any live provider call, filesystem dependency or PDF overlay implementation.
"""

from __future__ import annotations

import unicodedata

import pymupdf as fitz

from app.services.documents.pdf_processor import (
    _extract_block_text,
    _normalize_text,
    _validate_block,
)


def test_normalize_collapses_whitespace_and_line_breaks():
    assert _normalize_text("one two\nthree\tfour") == "one two three four"
    assert _normalize_text("  leading and trailing  ") == "leading and trailing"
    assert _normalize_text("a\u00a0b") == "a b"


def test_normalize_preserves_hyphens():
    assert _normalize_text("well-known") == "well-known"
    assert _normalize_text("co-operation") == "co-operation"


def test_normalize_applies_nfc():
    composed = "caf\u00e9"  # single code point
    decomposed = "cafe\u0301"  # e + combining acute
    assert unicodedata.normalize("NFC", composed) == unicodedata.normalize(
        "NFC", decomposed
    )
    assert _normalize_text(composed) == _normalize_text(decomposed)


def test_validate_accepts_identical_text():
    assert _validate_block("Hello world", "Hello world") is True


def test_validate_rejects_missing_final_word():
    assert _validate_block("The quick brown fox", "The quick brown") is False


def test_validate_rejects_missing_final_sentence():
    assert _validate_block(
        "First sentence. Second sentence.", "First sentence."
    ) is False


def test_validate_rejects_empty_rendered_text():
    assert _validate_block("Some translated text", "") is False


def test_validate_accepts_whitespace_and_line_break_differences():
    assert _validate_block("one two three", "one\ntwo three") is True


def test_validate_accepts_soft_hyphen_for_hyphen():
    assert _validate_block("DEMO-2026-0042", "DEMO\u00ad2026\u00ad0042") is True


def test_validate_still_rejects_missing_hyphen():
    assert _validate_block("DEMO-2026", "DEMO2026") is False


def test_validate_rejects_reordering():
    assert _validate_block("one two three", "three two one") is False


def test_validate_accepts_nfc_equivalent_text():
    composed = "caf\u00e9"
    decomposed = "cafe\u0301"
    assert _validate_block(composed, decomposed) is True


def test_validate_rejects_partial_word():
    assert _validate_block("translation", "translat") is False


def test_validate_rtl_equality():
    rtl = "\u0645\u0631\u062d\u0628\u0629"  # مرحبة
    assert _validate_block(rtl, rtl) is True


def test_validate_rtl_truncation_rejected():
    full = "\u0645\u0631\u062d\u0628\u0629 \u0628\u0627\u0644\u0639\u0631\u0628\u064a\u0629"
    truncated = "\u0645\u0631\u062d\u0628\u0629"
    assert _validate_block(full, truncated) is False


def test_extract_block_text_returns_words_in_rect():
    document = fitz.open()
    page = document.new_page(width=400, height=500)
    page.insert_text((36, 72), "Hello overlay world", fontsize=12, fontname="helv")
    rect = fitz.Rect(30, 60, 250, 90)
    try:
        text = _extract_block_text(page, rect)
        assert "Hello" in text
        assert "overlay" in text
        assert "world" in text
    finally:
        document.close()


def test_extract_block_text_excludes_outside_words():
    document = fitz.open()
    page = document.new_page(width=400, height=500)
    page.insert_text((36, 72), "Inside", fontsize=12, fontname="helv")
    page.insert_text((300, 72), "Outside", fontsize=12, fontname="helv")
    rect = fitz.Rect(30, 60, 120, 90)
    try:
        text = _extract_block_text(page, rect)
        assert "Inside" in text
        assert "Outside" not in text
    finally:
        document.close()


def test_validate_rtl_nfkc_presentation_form_equivalence():
    base = "مرحبة"
    assert _validate_block(base, base) is True


def test_validate_mixed_urdu_english_equality():
    mixed = "شرائط FOB Rotterdam 30 days"
    assert _validate_block(mixed, mixed) is True


def test_validate_mixed_urdu_english_truncation_rejected():
    full = "شرائط FOB Rotterdam 30 days"
    truncated = "شرائط FOB Rotterdam"
    assert _validate_block(full, truncated) is False


def test_validate_mixed_urdu_numbers_dates_preserved():
    text = "تاریخ 2 November 2026 قیمت 5000 USD"
    assert _validate_block(text, text) is True
    assert _validate_block(text, text.replace("5000", "4000")) is False
