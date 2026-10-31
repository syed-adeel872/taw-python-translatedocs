"""PDF text extraction and readable PDF reconstruction.

PDFs are rebuilt as text-based PDFs, one output page per source page (plus
continuation pages when translated text is longer). Page sizes are preserved.
Images, vector art, columns and exact fonts are not preserved.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import pymupdf as fitz

from app.config import Settings
from app.errors import (
    CorruptedDocumentError,
    DocumentProcessingError,
    PasswordProtectedError,
    ScannedPdfError,
)
from app.languages import RTL_LANGUAGES
from app.services.documents.base import ProcessResult
from app.services.documents.fonts import resolve_pdf_font
from app.services.translation.base import TranslationService

logger = logging.getLogger(__name__)

MARGIN = 36.0
MIN_FONT_SIZE = 7.0
MAX_FONT_SIZE = 22.0
LINE_FACTOR = 1.38


@dataclass(frozen=True)
class _Block:
    text: str
    font_size: float


@dataclass(frozen=True)
class _Page:
    width: float
    height: float
    blocks: list[_Block]


class PdfProcessor:
    def __init__(self, translator: TranslationService, settings: Settings) -> None:
        self.translator = translator
        self.settings = settings

    def process(
        self,
        input_path: Path,
        output_path: Path,
        source_language: str,
        target_language: str,
    ) -> ProcessResult:
        document = None
        try:
            document = fitz.open(str(input_path))
        except Exception as exc:
            raise CorruptedDocumentError(
                "The PDF file could not be opened. It may be corrupted."
            ) from exc

        if document.needs_pass:
            document.close()
            raise PasswordProtectedError()

        try:
            pages = _extract_pages(document)
        finally:
            document.close()

        source_texts = [block.text for page in pages for block in page.blocks]
        if not source_texts:
            raise ScannedPdfError()

        translations = self.translator.translate_texts(
            source_texts, source_language, target_language
        )

        translated_pages: list[_Page] = []
        cursor = 0
        for page in pages:
            blocks = []
            for block in page.blocks:
                blocks.append(_Block(translations[cursor], block.font_size))
                cursor += 1
            translated_pages.append(_Page(page.width, page.height, blocks))

        font_path = resolve_pdf_font(
            self.settings, "".join(block.text for page in translated_pages for block in page.blocks)
        )

        try:
            _build_pdf(
                translated_pages,
                output_path,
                font_path=font_path,
                rtl=target_language in RTL_LANGUAGES,
            )
        except DocumentProcessingError:
            raise
        except Exception as exc:
            logger.exception("PDF output generation failed")
            raise DocumentProcessingError(
                "The translated PDF file could not be generated."
            ) from exc

        warnings = [
            "The translated PDF is rebuilt as a readable text PDF. Original page "
            "sizes and page breaks are preserved where practical.",
            "Images, graphics, tables, multi-column layouts and exact fonts are not "
            "preserved in the translated PDF.",
            "Scanned PDFs without a text layer are not supported (no OCR).",
        ]
        if font_path is None:
            warnings.append("A built-in font was used; non-Latin scripts may not render.")
        else:
            warnings.append(
                "A Unicode font was embedded. Some complex scripts may not be shaped "
                "perfectly by the PDF engine."
            )

        return ProcessResult(
            characters=sum(len(text) for text in source_texts),
            segments=len(source_texts),
            warnings=warnings,
        )


def _extract_pages(document: fitz.Document) -> list[_Page]:
    pages: list[_Page] = []
    for page in document:
        raw = page.get_text("dict", sort=True)
        blocks: list[_Block] = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            lines: list[str] = []
            sizes: list[float] = []
            for line in block.get("lines", []):
                span_text = "".join(
                    span.get("text", "") for span in line.get("spans", [])
                ).strip()
                if span_text:
                    lines.append(span_text)
                for span in line.get("spans", []):
                    if span.get("text", "").strip():
                        sizes.append(float(span.get("size", 10.0)))
            text = " ".join(lines).strip()
            if not text:
                continue
            size = median(sizes) if sizes else 10.0
            size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, size))
            blocks.append(_Block(text=text, font_size=size))
        pages.append(_Page(width=page.rect.width, height=page.rect.height, blocks=blocks))
    return pages


def _build_pdf(
    pages: list[_Page],
    output_path: Path,
    *,
    font_path: str | None,
    rtl: bool,
) -> None:
    output = fitz.open()
    fontname = "F0" if font_path else "helv"
    font = fitz.Font(fontfile=font_path) if font_path else fitz.Font("helv")
    align = fitz.TEXT_ALIGN_RIGHT if rtl else fitz.TEXT_ALIGN_LEFT

    try:
        for source_page in pages:
            page = output.new_page(width=source_page.width, height=source_page.height)
            if font_path:
                page.insert_font(fontname=fontname, fontfile=font_path)
            y = MARGIN

            for block in source_page.blocks:
                available_width = max(20.0, source_page.width - 2 * MARGIN)
                lines = _wrap_text(block.text, font, block.font_size, available_width)
                height = max(block.font_size * LINE_FACTOR, len(lines) * block.font_size * LINE_FACTOR)
                height += block.font_size * 0.5

                bottom = source_page.height - MARGIN
                if y + height > bottom:
                    if y > MARGIN:
                        page = output.new_page(
                            width=source_page.width, height=source_page.height
                        )
                        if font_path:
                            page.insert_font(fontname=fontname, fontfile=font_path)
                        y = MARGIN

                rect = fitz.Rect(
                    MARGIN, y, source_page.width - MARGIN, y + height
                )
                result = page.insert_textbox(
                    rect,
                    block.text,
                    fontsize=block.font_size,
                    fontname=fontname,
                    fontfile=font_path,
                    align=align,
                    color=(0.08, 0.1, 0.12),
                )

                if result < 0:
                    extra = _wrap_text(
                        block.text,
                        font,
                        block.font_size,
                        max(20.0, source_page.width - 2 * MARGIN),
                        generous=True,
                    )
                    rect = fitz.Rect(
                        MARGIN,
                        y,
                        source_page.width - MARGIN,
                        min(
                            source_page.height - MARGIN,
                            y + (len(extra) + 2) * block.font_size * LINE_FACTOR,
                        ),
                    )
                    page.insert_textbox(
                        rect,
                        block.text,
                        fontsize=block.font_size,
                        fontname=fontname,
                        fontfile=font_path,
                        align=align,
                        color=(0.08, 0.1, 0.12),
                    )
                    height = rect.height

                y += height + block.font_size * 0.45

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output.save(str(output_path), garbage=3, deflate=True)
    finally:
        output.close()


def _wrap_text(
    text: str, font: fitz.Font, font_size: float, width: float, generous: bool = False
) -> list[str]:
    factor = 0.92 if generous else 1.0
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.text_length(candidate, fontsize=font_size) <= width * factor:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word

        while font.text_length(current, fontsize=font_size) > width * factor:
            cut = _longest_prefix(font, current, font_size, width * factor)
            lines.append(current[:cut])
            current = current[cut:]

    if current:
        lines.append(current)
    return lines or [""]


def _longest_prefix(font: fitz.Font, text: str, font_size: float, width: float) -> int:
    low, high = 1, len(text)
    best = 1
    while low <= high:
        middle = (low + high) // 2
        if font.text_length(text[:middle], fontsize=font_size) <= width:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    return max(1, best)
