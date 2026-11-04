"""Shared document processor result type."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OverflowBlock:
    """A translated block that could not be rendered in its original region.

    Recorded when overlay placement fails even after the font-size fallback
    reaches the minimum. The presence of any entry is a job failure condition;
    this is a record of the failure, not a guarantee that the text was emitted.
    """

    page: int
    block: int
    rect: list[float]
    text: str
    font_size: float
    reason: str


@dataclass
class ProcessResult:
    characters: int = 0
    segments: int = 0
    warnings: list[str] = field(default_factory=list)
    overflow_blocks: list[OverflowBlock] = field(default_factory=list)
