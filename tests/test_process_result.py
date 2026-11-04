"""Focused tests for the ProcessResult / OverflowBlock schema."""

from __future__ import annotations

from app.services.documents.base import OverflowBlock, ProcessResult


def test_overflow_block_has_required_fields():
    block = OverflowBlock(
        page=0,
        block=2,
        rect=[36.0, 59.0, 200.0, 100.0],
        text="translated text",
        font_size=7.0,
        reason="exceeds_min_font",
    )
    assert block.page == 0
    assert block.block == 2
    assert block.rect == [36.0, 59.0, 200.0, 100.0]
    assert block.text == "translated text"
    assert block.font_size == 7.0
    assert block.reason == "exceeds_min_font"


def test_process_result_defaults_to_empty_overflow():
    result = ProcessResult()
    assert result.overflow_blocks == []
    assert result.characters == 0
    assert result.segments == 0
    assert result.warnings == []


def test_process_result_can_hold_overflow_blocks():
    block = OverflowBlock(
        page=1,
        block=0,
        rect=[10.0, 10.0, 50.0, 50.0],
        text="x",
        font_size=7.0,
        reason="exceeds_min_font",
    )
    result = ProcessResult(characters=5, segments=1, overflow_blocks=[block])
    assert len(result.overflow_blocks) == 1
    assert result.overflow_blocks[0].page == 1
    assert result.characters == 5
