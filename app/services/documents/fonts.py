"""Locate a TrueType font that can render the translated PDF text."""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from app.config import Settings
from app.errors import DocumentProcessingError

_FONT_CANDIDATES = [
    # Explicit setting is handled first.
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\arialuni.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\Nirmala.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    r"C:\Windows\Fonts\malgun.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def resolve_pdf_font(settings: Settings, translated_text: str) -> str | None:
    """Return a font file path that covers the needed characters.

    Returns ``None`` when the text is pure ASCII, in which case PyMuPDF's
    built-in Helvetica can be used.
    """
    required = {character for character in translated_text if ord(character) > 127}

    candidates: list[Path] = []
    if settings.pdf_font_path:
        configured = Path(settings.pdf_font_path)
        if not configured.is_absolute():
            configured = (Path.cwd() / configured).resolve()
        candidates.append(configured)
    candidates.extend(Path(path) for path in _FONT_CANDIDATES)

    fallback: str | None = None
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            font = fitz.Font(fontfile=str(candidate))
        except Exception:
            continue

        if fallback is None:
            fallback = str(candidate)

        if not required:
            return str(candidate)

        if all(font.has_glyph(ord(character)) for character in required):
            return str(candidate)

    if not required:
        return fallback

    raise DocumentProcessingError(
        "The translated PDF contains characters that no available font can render. "
        "Install a Unicode font and set PDF_FONT_PATH in .env."
    )
