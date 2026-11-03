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


def _load_font(path: Path) -> fitz.Font | None:
    """Return a usable PyMuPDF font for ``path``, or ``None`` if it cannot load."""
    try:
        return fitz.Font(fontfile=str(path))
    except Exception:
        return None


def _candidate_paths(settings: Settings) -> list[Path]:
    """Return the ordered list of font paths to inspect."""
    candidates: list[Path] = []
    if settings.pdf_font_path:
        configured = Path(settings.pdf_font_path)
        if not configured.is_absolute():
            configured = (Path.cwd() / configured).resolve()
        candidates.append(configured)
    candidates.extend(Path(path) for path in _FONT_CANDIDATES)
    return candidates


def resolve_pdf_font(settings: Settings, translated_text: str) -> str | None:
    """Return a font file path that covers the needed characters.

    Returns ``None`` when the text is pure ASCII, in which case PyMuPDF's
    built-in Helvetica can be used.

    Raises ``DocumentProcessingError`` when the text contains non-ASCII
    characters and no available font can render every one of them.
    """
    required = {character for character in translated_text if ord(character) > 127}

    candidates = _candidate_paths(settings)
    configured_path = candidates[0] if settings.pdf_font_path else None

    fallback: str | None = None
    configured_failed = False

    for candidate in candidates:
        if not candidate.is_file():
            if candidate == configured_path:
                configured_failed = True
            continue

        font = _load_font(candidate)
        if font is None:
            if candidate == configured_path:
                configured_failed = True
            continue

        if fallback is None:
            fallback = str(candidate)

        if not required:
            return str(candidate)

        if all(font.has_glyph(ord(character)) for character in required):
            return str(candidate)

    if not required:
        return fallback

    hint = ""
    if configured_path is not None and configured_failed:
        hint = (
            " The configured PDF_FONT_PATH could not be used; install a Unicode "
            "TrueType font and set PDF_FONT_PATH to its path."
        )
    raise DocumentProcessingError(
        "The translated PDF contains characters that no available font can render."
        f"{hint}"
    )
