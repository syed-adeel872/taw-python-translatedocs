"""Focused unit tests for PDF overlay geometry, colour and font helpers.

These tests exercise the pure helpers and ``_overlay_block`` directly with
synthetic PyMuPDF objects. No live provider, filesystem fixture or full
``process()`` wiring is involved.
"""

from __future__ import annotations

import pymupdf as fitz
import pytest

from app.services.documents.pdf_processor import (
    _Block,
    _Span,
    _background_color,
    _block_union_rect,
    _choose_text_color,
    _contrast_ratio,
    _drawing_fill_is_white,
    _font_size_candidates,
    _is_large_text,
    _minimum_font_size,
    _overlay_block,
    _rects_overlap,
    _redaction_rect,
)


def _span(
    text: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    size: float = 12.0,
    color: int = 0,
    flags: int = 0,
) -> _Span:
    return _Span(
        text=text,
        rect=fitz.Rect(x0, y0, x1, y1),
        size=size,
        color=color,
        font="helv",
        flags=flags,
    )


def _block(spans, font_size=12.0, text="source text") -> _Block:
    return _Block(text=text, font_size=font_size, spans=spans)


def _page(width=400, height=500) -> fitz.Document:
    document = fitz.open()
    document.new_page(width=width, height=height)
    return document


def test_block_union_rect_is_tight_bounding_box():
    block = type(
        "_B",
        (),
        {"spans": [_span("a", 10, 20, 30, 40), _span("b", 50, 60, 70, 80)]},
    )()
    rect = _block_union_rect(block)
    assert (rect.x0, rect.y0, rect.x1, rect.y1) == (10, 20, 70, 80)


def test_block_union_rect_single_span():
    block = type("_B", (), {"spans": [_span("a", 10, 20, 30, 40)]})()
    rect = _block_union_rect(block)
    assert (rect.x0, rect.y0, rect.x1, rect.y1) == (10, 20, 30, 40)


def test_block_union_rect_no_spans_returns_empty_rect():
    block = type("_B", (), {"spans": []})()
    rect = _block_union_rect(block)
    assert (rect.x0, rect.y0, rect.x1, rect.y1) == (0.0, 0.0, 0.0, 0.0)


def test_rects_overlap_genuine_intersection():
    assert _rects_overlap(fitz.Rect(0, 0, 10, 10), fitz.Rect(5, 5, 15, 15)) is True


def test_rects_overlap_fully_contained_returns_true():
    assert _rects_overlap(fitz.Rect(0, 0, 20, 20), fitz.Rect(5, 5, 10, 10)) is True
    assert _rects_overlap(fitz.Rect(5, 5, 10, 10), fitz.Rect(0, 0, 20, 20)) is True


def test_rects_overlap_touching_edges_are_not_overlaps():
    assert _rects_overlap(fitz.Rect(0, 0, 10, 10), fitz.Rect(10, 0, 20, 10)) is False
    assert _rects_overlap(fitz.Rect(0, 0, 10, 10), fitz.Rect(0, 10, 10, 20)) is False


def test_rects_overlap_disjoint():
    assert _rects_overlap(fitz.Rect(0, 0, 5, 5), fitz.Rect(10, 10, 15, 15)) is False


def test_redaction_rect_adds_safety_padding():
    block = _block([_span("src", 10, 20, 30, 40)])
    rect = _redaction_rect(block)
    assert (rect.x0, rect.y0, rect.x1, rect.y1) == (9.5, 19.5, 30.5, 40.5)


def test_drawing_fill_is_white_for_none():
    assert _drawing_fill_is_white(None) is True


def test_drawing_fill_is_white_for_white():
    assert _drawing_fill_is_white((1.0, 1.0, 1.0)) is True
    assert _drawing_fill_is_white((0.999, 1.0, 1.0)) is True


def test_drawing_fill_is_white_rejects_coloured():
    assert _drawing_fill_is_white((0.5, 0.5, 0.5)) is False
    assert _drawing_fill_is_white((1.0, 0.0, 0.0)) is False


def test_drawing_fill_is_white_handles_short_tuples():
    assert _drawing_fill_is_white((1.0,)) is True
    assert _drawing_fill_is_white((1.0, 1.0)) is True


def test_minimum_font_size_policy():
    assert _minimum_font_size(7.0) == 7.0
    assert _minimum_font_size(8.0) == 8.0
    assert _minimum_font_size(10.0) == 8.0
    assert _minimum_font_size(12.0) == 9.6
    assert _minimum_font_size(20.0) == 16.0


def test_font_size_candidates_descend_to_policy_floor():
    candidates = _font_size_candidates(12.0)
    assert candidates[0] == 12.0
    assert candidates[-1] == 9.6
    assert candidates == sorted(candidates, reverse=True)
    assert all(9.6 <= size <= 12.0 for size in candidates)


def test_font_size_candidates_keep_original_below_minimum():
    assert _font_size_candidates(7.0) == [7.0]


def test_font_size_candidates_never_scale_below_eight_for_normal_text():
    candidates = _font_size_candidates(8.0)
    assert candidates == [8.0]


def test_contrast_ratio_black_on_white():
    assert _contrast_ratio((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)) == pytest.approx(21.0)


def test_large_text_detection_regular_and_bold_thresholds():
    regular_18 = _block([_span("a", 0, 0, 1, 1, size=18.0)], font_size=18.0)
    regular_17 = _block([_span("a", 0, 0, 1, 1, size=17.0)], font_size=17.0)
    bold_14 = _block([_span("a", 0, 0, 1, 1, size=14.0, flags=16)], font_size=14.0)
    bold_13 = _block([_span("a", 0, 0, 1, 1, size=13.0, flags=16)], font_size=13.0)
    assert _is_large_text(regular_18) is True
    assert _is_large_text(regular_17) is False
    assert _is_large_text(bold_14) is True
    assert _is_large_text(bold_13) is False


def test_large_text_requires_every_span_to_qualify():
    block = _block(
        [
            _span("a", 0, 0, 1, 1, size=18.0),
            _span("b", 0, 0, 1, 1, size=12.0),
        ],
        font_size=15.0,
    )
    assert _is_large_text(block) is False


def test_choose_text_color_keeps_original_when_contrast_is_adequate():
    block = _block([_span("src", 0, 0, 1, 1, color=0)])
    color, reason = _choose_text_color(block, (1.0, 1.0, 1.0))
    assert color == (0.0, 0.0, 0.0)
    assert reason is None


def test_choose_text_color_replaces_low_contrast_text():
    white = 0xFFFFFF
    block = _block([_span("src", 0, 0, 1, 1, color=white)])
    color, reason = _choose_text_color(block, (1.0, 1.0, 1.0))
    assert color == (0.0, 0.0, 0.0)
    assert reason is None


def test_choose_text_color_uses_least_favourable_span():
    block = _block(
        [
            _span("good", 0, 0, 1, 1, color=0),
            _span("bad", 0, 0, 1, 1, color=0x777777),
        ]
    )
    color, reason = _choose_text_color(block, (1.0, 1.0, 1.0))
    assert color == (0.0, 0.0, 0.0)
    assert reason is None


def test_choose_text_color_uses_white_on_dark_background_when_original_fails():
    block = _block([_span("src", 0, 0, 1, 1, color=0)])
    color, reason = _choose_text_color(block, (0.02, 0.02, 0.02))
    assert color == (1.0, 1.0, 1.0)
    assert reason is None


def test_background_color_plain_page_is_white():
    document = _page()
    try:
        background, reason = _background_color(document[0], fitz.Rect(30, 60, 120, 90))
        assert background == (1.0, 1.0, 1.0)
        assert reason is None
    finally:
        document.close()


def test_background_color_accepts_solid_coloured_fill():
    document = _page()
    page = document[0]
    page.draw_rect(
        fitz.Rect(30, 60, 120, 90), color=None, fill=(0.8, 0.2, 0.2)
    )
    try:
        background, reason = _background_color(page, fitz.Rect(30, 60, 120, 90))
        assert background == pytest.approx((0.8, 0.2, 0.2))
        assert reason is None
    finally:
        document.close()


def test_background_color_accepts_fill_outside_block():
    document = _page()
    page = document[0]
    page.draw_rect(
        fitz.Rect(200, 200, 280, 260), color=None, fill=(0.8, 0.2, 0.2)
    )
    try:
        background, reason = _background_color(page, fitz.Rect(30, 60, 120, 90))
        assert background == (1.0, 1.0, 1.0)
        assert reason is None
    finally:
        document.close()


def test_background_color_rejects_partial_fill_coverage():
    document = _page()
    page = document[0]
    page.draw_rect(
        fitz.Rect(30, 60, 80, 90), color=None, fill=(0.8, 0.2, 0.2)
    )
    try:
        background, reason = _background_color(page, fitz.Rect(30, 60, 120, 90))
        assert background is None
        assert reason == "uncertain_background"
    finally:
        document.close()


def test_background_color_rejects_translucent_fill():
    document = _page()
    page = document[0]
    page.draw_rect(
        fitz.Rect(30, 60, 120, 90),
        color=None,
        fill=(0.8, 0.2, 0.2),
        fill_opacity=0.5,
    )
    try:
        background, reason = _background_color(page, fitz.Rect(30, 60, 120, 90))
        assert background is None
        assert reason == "uncertain_background"
    finally:
        document.close()


def test_background_color_rejects_overlapping_image():
    document = _page()
    page = document[0]
    samples = bytes([0] * (10 * 10 * 3))
    pix = fitz.Pixmap(fitz.csRGB, 10, 10, samples, 0)
    page.insert_image(fitz.Rect(30, 60, 80, 80), stream=pix.tobytes("png"))
    try:
        background, reason = _background_color(page, fitz.Rect(30, 60, 120, 90))
        assert background is None
        assert reason == "raster_image"
    finally:
        document.close()
        pix = None


def test_background_color_accepts_image_outside_block():
    document = _page()
    page = document[0]
    samples = bytes([0] * (10 * 10 * 3))
    pix = fitz.Pixmap(fitz.csRGB, 10, 10, samples, 0)
    page.insert_image(fitz.Rect(200, 200, 230, 230), stream=pix.tobytes("png"))
    try:
        background, reason = _background_color(page, fitz.Rect(30, 60, 120, 90))
        assert background == (1.0, 1.0, 1.0)
        assert reason is None
    finally:
        document.close()
        pix = None


def test_background_color_image_detection_failure_is_unsafe(monkeypatch):
    document = _page()
    page = document[0]

    def _raise(*args, **kwargs):
        raise RuntimeError("image inspection failed")

    monkeypatch.setattr(page, "get_image_info", _raise)
    try:
        background, reason = _background_color(page, fitz.Rect(30, 60, 120, 90))
        assert background is None
        assert reason == "uncertain_background"
    finally:
        document.close()


def _recording_insert_textbox(page, *, fail_above: float | None = None):
    calls = []

    def _insert(rect, text, **kwargs):
        calls.append({"rect": fitz.Rect(rect), "text": text, **kwargs})
        if fail_above is not None and kwargs["fontsize"] > fail_above:
            return -1
        return 0

    page.insert_textbox = _insert
    return calls


def test_overlay_block_inserts_text_and_returns_none():
    document = _page()
    page = document[0]
    block = _block([_span("src", 36, 60, 200, 90)], font_size=12.0)
    calls = _recording_insert_textbox(page)
    try:
        result = _overlay_block(
            page, 0, block, "translated text", "helv", None, False, (0.0, 0.0, 0.0)
        )
        assert result is None
        assert len(calls) == 1
        assert calls[0]["text"] == "translated text"
        assert calls[0]["fontsize"] == 12.0
        assert calls[0]["color"] == (0.0, 0.0, 0.0)
    finally:
        document.close()


def test_overlay_block_reduces_font_to_fit():
    document = _page()
    page = document[0]
    block = _block([_span("src", 36, 60, 200, 90)], font_size=12.0)
    calls = _recording_insert_textbox(page, fail_above=10.0)
    try:
        result = _overlay_block(
            page, 0, block, "translated text", "helv", None, False, (0.0, 0.0, 0.0)
        )
        assert result is None
        assert calls[-1]["fontsize"] == 10.0
        assert [call["fontsize"] for call in calls] == [12.0, 11.5, 11.0, 10.5, 10.0]
    finally:
        document.close()


def test_overlay_block_returns_overflow_at_policy_minimum():
    document = _page()
    page = document[0]
    block = _block([_span("src", 36, 60, 37, 61)], font_size=12.0)
    _recording_insert_textbox(page, fail_above=-1.0)
    try:
        result = _overlay_block(
            page,
            5,
            block,
            "a long translated phrase here",
            "helv",
            None,
            False,
            (0.0, 0.0, 0.0),
        )
        assert result is not None
        assert result.font_size == 9.6
        assert result.reason == "exceeds_min_font"
        assert result.block == 5
        assert result.page == 0
        assert result.text == "a long translated phrase here"
    finally:
        document.close()


def test_overlay_block_keeps_original_floor_for_tiny_fonts():
    document = _page()
    page = document[0]
    block = _block([_span("src", 36, 60, 37, 61, size=7.0)], font_size=7.0)
    calls = _recording_insert_textbox(page, fail_above=-1.0)
    try:
        result = _overlay_block(
            page, 0, block, "too long", "helv", None, False, (0.0, 0.0, 0.0)
        )
        assert result is not None
        assert result.font_size == 7.0
        assert calls[0]["fontsize"] == 7.0
    finally:
        document.close()


def test_overlay_block_uses_left_alignment_for_ltr():
    document = _page()
    page = document[0]
    block = _block([_span("src", 36, 60, 200, 90)], font_size=12.0)
    calls = _recording_insert_textbox(page)
    try:
        _overlay_block(
            page, 0, block, "translated text", "helv", None, False, (0.0, 0.0, 0.0)
        )
        assert calls[0]["align"] == fitz.TEXT_ALIGN_LEFT
    finally:
        document.close()


def test_overlay_block_uses_right_alignment_for_rtl():
    document = _page()
    page = document[0]
    block = _block([_span("src", 36, 60, 200, 90)], font_size=12.0)
    calls = _recording_insert_textbox(page)
    try:
        _overlay_block(
            page, 0, block, "translated text", "helv", None, True, (0.0, 0.0, 0.0)
        )
        assert calls[0]["align"] == fitz.TEXT_ALIGN_RIGHT
    finally:
        document.close()


def test_overlay_block_uses_original_block_rectangle():
    document = _page()
    page = document[0]
    spans = [_span("a", 10, 20, 30, 40), _span("b", 50, 60, 70, 80)]
    block = _block(spans, font_size=12.0)
    calls = _recording_insert_textbox(page)
    try:
        _overlay_block(
            page, 0, block, "translated text", "helv", None, False, (0.0, 0.0, 0.0)
        )
        expected = _block_union_rect(block)
        actual = calls[0]["rect"]
        assert (actual.x0, actual.y0, actual.x1, actual.y1) == (
            expected.x0,
            expected.y0,
            expected.x1,
            expected.y1,
        )
    finally:
        document.close()
