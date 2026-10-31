"""Shared document processor result type."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProcessResult:
    characters: int = 0
    segments: int = 0
    warnings: list[str] = field(default_factory=list)
