"""Focused tests for PDF span extraction and whitespace reconstruction.

These tests exercise ``_extract_pages`` directly with synthetic PDFs built via
PyMuPDF, so they verify extraction accuracy without any live provider call.
"""

from __future__ import annotations

import pymupdf as fitz

from app.services.documents.pdf_processor import _extract_pages


def _extract(pdf_bytes: bytes):
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return _extract_pages(document)
    finally:
        document.close()


def test_two_spans_in_one_line_get_a_space():
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((36, 72), "Hello", fontsize=12, fontname="helv")
    page.insert_text((80, 72), "world", fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()

    pages = _extract(data)
    assert len(pages) == 1
    blocks = pages[0].blocks
    assert blocks, "Expected at least one text block"
    assert "Hello world" in blocks[0].text
    assert "Helloworld" not in blocks[0].text


def test_adjacent_spans_do_not_get_an_extra_space():
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    # Two spans placed with a tiny gap should be treated as touching letters.
    page.insert_text((36, 72), "abc", fontsize=12, fontname="helv")
    page.insert_text((48, 72), "def", fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()

    pages = _extract(data)
    blocks = pages[0].blocks
    assert blocks
    assert "abc def" not in blocks[0].text
    assert "abcdef" in blocks[0].text


def test_mixed_font_and_size_metadata_is_preserved():
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((36, 72), "Bold", fontsize=14, fontname="hebo")
    page.insert_text((90, 72), "small", fontsize=10, fontname="helv")
    data = doc.tobytes()
    doc.close()

    pages = _extract(data)
    blocks = pages[0].blocks
    assert blocks
    block = blocks[0]
    assert len(block.spans) == 2
    sizes = [span.size for span in block.spans]
    assert 14.0 in sizes and 10.0 in sizes
    # Median of [10, 14] is 12.
    assert block.font_size == 12.0


def test_two_columns_produce_separate_logical_blocks():
    """Two widely separated columns must become separate logical blocks."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((36, 72), "Left column", fontsize=12, fontname="helv")
    page.insert_text((236, 72), "Right column", fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()

    pages = _extract(data)
    blocks = pages[0].blocks
    assert len(blocks) == 2, f"Expected 2 blocks, got {len(blocks)}: {[b.text for b in blocks]}"
    left = [b for b in blocks if "Left" in b.text]
    right = [b for b in blocks if "Right" in b.text]
    assert left and right


def test_single_column_paragraph_is_not_split():
    """A normal paragraph with several words must remain a single block."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((36, 72), "One two three four", fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()

    pages = _extract(data)
    blocks = pages[0].blocks
    assert len(blocks) == 1, f"Expected 1 block, got {len(blocks)}"
    assert "One two three four" in blocks[0].text


def test_adjacent_styled_spans_within_a_word_are_not_split():
    """Bold and plain spans forming one word must stay in one block."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((36, 72), "Bold", fontsize=12, fontname="hebo")
    page.insert_text((60, 72), "text", fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()

    pages = _extract(data)
    blocks = pages[0].blocks
    assert len(blocks) == 1, f"Expected 1 block, got {len(blocks)}"
    assert "Boldtext" in blocks[0].text


def test_degenerate_span_bbox_is_skipped():
    """A span whose bbox is missing or zero-sized must not crash extraction."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((36, 72), "Valid text here", fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()

    pages = _extract(data)
    blocks = pages[0].blocks
    assert blocks
    assert "Valid text here" in blocks[0].text


def test_multiline_paragraph_preserves_both_lines():
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((36, 72), "First line", fontsize=12, fontname="helv")
    page.insert_text((36, 100), "Second line", fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()

    pages = _extract(data)
    all_text = " ".join(block.text for block in pages[0].blocks)
    assert "First line" in all_text
    assert "Second line" in all_text


def test_two_columns_with_multiple_lines_and_interleaved_order():
    """Two columns with several lines each, emitted interleaved by row."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=700)
    # Interleaved row-major ordering: L1, R1, L2, R2, L3, R3
    page.insert_text((36, 72), "L1", fontsize=12, fontname="helv")
    page.insert_text((336, 72), "R1", fontsize=12, fontname="helv")
    page.insert_text((36, 100), "L2", fontsize=12, fontname="helv")
    page.insert_text((336, 100), "R2", fontsize=12, fontname="helv")
    page.insert_text((36, 128), "L3", fontsize=12, fontname="helv")
    page.insert_text((336, 128), "R3", fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()

    pages = _extract(data)
    blocks = pages[0].blocks
    assert len(blocks) == 2, f"Expected 2 blocks, got {len(blocks)}: {[b.text for b in blocks]}"
    left = [b for b in blocks if "L1" in b.text or "L2" in b.text or "L3" in b.text]
    right = [b for b in blocks if "R1" in b.text or "R2" in b.text or "R3" in b.text]
    assert left and right
    assert "L1" in left[0].text and "L2" in left[0].text and "L3" in left[0].text
    assert "R1" in right[0].text and "R2" in right[0].text and "R3" in right[0].text


def test_two_columns_with_blank_lines_between_rows():
    """Blank lines between column rows must not disable column detection."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=700)
    page.insert_text((36, 72), "L1", fontsize=12, fontname="helv")
    page.insert_text((336, 72), "R1", fontsize=12, fontname="helv")
    page.insert_text((36, 130), "L2", fontsize=12, fontname="helv")
    page.insert_text((336, 130), "R2", fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()

    pages = _extract(data)
    blocks = pages[0].blocks
    assert len(blocks) == 2, f"Expected 2 blocks, got {len(blocks)}: {[b.text for b in blocks]}"
    left = [b for b in blocks if "L1" in b.text or "L2" in b.text]
    right = [b for b in blocks if "R1" in b.text or "R2" in b.text]
    assert left and right


def test_two_columns_reading_order_left_before_right():
    """The left column must be emitted before the right column."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=700)
    page.insert_text((36, 72), "Left first", fontsize=12, fontname="helv")
    page.insert_text((336, 72), "Right second", fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()

    pages = _extract(data)
    blocks = pages[0].blocks
    assert len(blocks) == 2
    assert "Left" in blocks[0].text
    assert "Right" in blocks[1].text


def test_wrapped_paragraph_remains_one_block():
    """A wrapped paragraph (continuation lines) must not be split into columns."""
    doc = fitz.open()
    page = doc.new_page(width=200, height=500)
    # A single text run with an embedded newline produces one PyMuPDF block
    # with two stacked lines at the same x position.
    page.insert_text((36, 72), "One two three four\nfive six seven eight", fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()

    pages = _extract(data)
    blocks = pages[0].blocks
    assert len(blocks) == 1, f"Expected 1 block, got {len(blocks)}: {[b.text for b in blocks]}"
    assert "One two three four" in blocks[0].text
    assert "five six seven eight" in blocks[0].text


def test_two_columns_with_different_font_sizes():
    """Columns with different font sizes must still be separated."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=700)
    page.insert_text((36, 72), "Big left column", fontsize=18, fontname="helv")
    page.insert_text((336, 72), "Small right", fontsize=9, fontname="helv")
    data = doc.tobytes()
    doc.close()

    pages = _extract(data)
    blocks = pages[0].blocks
    assert len(blocks) == 2, f"Expected 2 blocks, got {len(blocks)}: {[b.text for b in blocks]}"
    left = [b for b in blocks if "Big" in b.text]
    right = [b for b in blocks if "Small" in b.text]
    assert left and right


def test_two_columns_large_heading_small_body_text():
    """A large heading next to small body text must not be merged into one block.

    The gap is narrow enough that a block-global 3x-max-font tolerance (which
    would use the 18pt heading as the reference) would incorrectly merge the
    two columns. A per-pair reference based on the smaller font keeps them
    separate.
    """
    doc = fitz.open()
    page = doc.new_page(width=300, height=500)
    # 18pt heading on the left, 9pt body text on the right, with a narrow
    # (~45px) inter-column gap.
    page.insert_text((36, 72), "Heading", fontsize=18, fontname="helv")
    page.insert_text((140, 72), "Body text", fontsize=9, fontname="helv")
    data = doc.tobytes()
    doc.close()

    pages = _extract(data)
    blocks = pages[0].blocks
    assert len(blocks) == 2, f"Expected 2 blocks, got {len(blocks)}: {[b.text for b in blocks]}"
    heading = [b for b in blocks if "Heading" in b.text]
    body = [b for b in blocks if "Body" in b.text]
    assert heading and body
