"""PDF text extraction and in-place overlay translation.

The source document is cloned, original text is removed with PyMuPDF
redactions that leave images and vector art untouched, and translated text is
inserted into the original text regions. Text over raster images or uncertain
backgrounds is rejected rather than rebuilt.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass, field
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
from app.services.documents.base import OverflowBlock, ProcessResult
from app.services.documents.fonts import resolve_pdf_font
from app.services.translation.base import TranslationService

logger = logging.getLogger(__name__)

MIN_FONT_SIZE = 8.0
MAX_FONT_SHRINK_RATIO = 0.8
NORMAL_TEXT_CONTRAST = 4.5
LARGE_TEXT_CONTRAST = 3.0
REDACTION_PADDING = 0.5


@dataclass(frozen=True)
class _Block:
    text: str
    font_size: float
    spans: list[_Span] = field(default_factory=list)


@dataclass(frozen=True)
class _Span:
    text: str
    rect: fitz.Rect
    size: float
    color: int
    font: str
    flags: int


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
        clone = None
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
            # Create an independent clone while the original is still open,
            # ahead of the overlay stage. The clone is closed in the finally
            # block below on both success and failure.
            clone = _clone_document(document)
        finally:
            document.close()

        try:
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
                    blocks.append(
                        _Block(translations[cursor], block.font_size, spans=block.spans)
                    )
                    cursor += 1
                translated_pages.append(_Page(page.width, page.height, blocks))

            font_path = resolve_pdf_font(
                self.settings,
                "".join(block.text for page in translated_pages for block in page.blocks),
            )

            output_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                _overlay_pdf(
                    clone,
                    translated_pages,
                    translations,
                    output_path,
                    font_path=font_path,
                    rtl=target_language in RTL_LANGUAGES,
                )
            except DocumentProcessingError:
                _remove_partial_output(output_path)
                raise
            except Exception as exc:
                _remove_partial_output(output_path)
                logger.exception("PDF overlay generation failed")
                raise DocumentProcessingError(
                    "The translated PDF file could not be generated."
                ) from exc

            warnings = [
                "The translated PDF preserves the original page count, page sizes, "
                "images, vector graphics and detected solid backgrounds where safe.",
                "Text blocks over raster images or uncertain backgrounds are rejected "
                "instead of being rebuilt.",
                "Original PDF text is removed with redaction. Text baked into raster "
                "image pixels is not removed.",
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
        finally:
            if clone is not None:
                clone.close()


def _span_gap_is_space(prev: _Span, next_span: _Span) -> bool:
    """Return True when the horizontal gap between two spans indicates a space.

    Uses span geometry and font size rather than blindly inserting a space for
    every positive x-coordinate gap. A space character is roughly a quarter of
    the font size wide, so gaps below that threshold are treated as touching
    letters (no space inserted).
    """
    gap = next_span.rect.x0 - prev.rect.x1
    if gap <= 0:
        return False
    reference = max(prev.size, next_span.size)
    return gap >= 0.25 * reference


def _split_columns(line_spans: list[_Span]) -> list[list[_Span]]:
    """Split a line's spans into column groups where a wide gap separates them.

    Uses the distribution of inter-span gaps within the line rather than a fixed
    page-width threshold. When several gaps exist, a gap larger than 3x the
    median positive gap is treated as a column separator. When only one gap
    exists, it is compared against 1.5x the font size. Normal paragraphs and
    adjacent styled spans are preserved.
    """
    if len(line_spans) <= 1:
        return [line_spans]

    gaps = []
    for prev, next_span in zip(line_spans, line_spans[1:]):
        gap = next_span.rect.x0 - prev.rect.x1
        if gap > 0:
            gaps.append(gap)
    if not gaps:
        return [line_spans]

    if len(gaps) == 1:
        threshold = 1.5 * max(prev.size for prev in line_spans)
    else:
        gaps.sort()
        median_gap = gaps[len(gaps) // 2]
        threshold = max(3.0 * median_gap, 1.5 * max(prev.size for prev in line_spans))

    groups: list[list[_Span]] = []
    current = [line_spans[0]]
    for prev, next_span in zip(line_spans, line_spans[1:]):
        gap = next_span.rect.x0 - prev.rect.x1
        if gap > threshold:
            groups.append(current)
            current = [next_span]
        else:
            current.append(next_span)
    groups.append(current)
    return groups


def _flush_columns(columns, col_x0, sizes, blocks):
    """Emit one ``_Block`` per accumulated column, left to right."""
    order = sorted(range(len(columns)), key=lambda i: col_x0[i])
    for idx in order:
        cluster = columns[idx]
        cluster_spans: list[_Span] = []
        line_texts: list[str] = []
        for group in cluster:
            parts: list[str] = []
            for i, span in enumerate(group):
                if i > 0 and _span_gap_is_space(group[i - 1], span):
                    parts.append(" ")
                parts.append(span.text)
            if parts:
                line_texts.append("".join(parts))
                cluster_spans.extend(group)
        if not cluster_spans:
            continue
        text = " ".join(line_texts)
        size = median(sizes) if sizes else 10.0
        size = max(1.0, size)
        blocks.append(_Block(text=text, font_size=size, spans=cluster_spans))


def _clone_document(document: fitz.Document) -> fitz.Document:
    """Return an independent copy of an open PDF document.

    The clone is created by serialising the source to bytes and reopening it,
    so the two documents share no underlying objects: closing or mutating one
    has no effect on the other. The original must remain open until the clone
    has been created.
    """
    return fitz.open(stream=document.tobytes(), filetype="pdf")


def _is_rtl_text(text: str) -> bool:
    """Return True when ``text`` contains RTL script characters."""
    return any(
        "\u0590" <= char <= "\u08ff" or "\ufb1d" <= char <= "\ufdff"
        for char in text
    )


def _normalize_text(text: str) -> str:
    """Normalize text for strict overlay validation.

    Applies Unicode normalization and collapses all whitespace runs (including
    non-breaking spaces and line breaks) to single spaces. Soft hyphens are
    treated as ordinary hyphens because PDF font encoding can emit them for
    hyphen glyphs.

    For text containing RTL scripts, NFKC is used so that Arabic presentation
    forms emitted by font shaping normalize back to their base letters before
    comparison. LTR text keeps the stricter NFC normalization. Other character
    differences remain strict validation failures.
    """
    if _is_rtl_text(text):
        normalized = unicodedata.normalize("NFKC", text)
    else:
        normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.replace("\u00ad", "-")
    return " ".join(normalized.split())


def _validate_block(expected: str, rendered: str) -> bool:
    """Return True only when the rendered text matches the expected text.

    Comparison is strict after normalization: whitespace and Unicode
    composition differences are tolerated, but any missing, extra or
    reordered character -- including a truncated trailing word or sentence --
    causes rejection. Ordinary hyphens are preserved and must match.
    """
    return _normalize_text(expected) == _normalize_text(rendered)


def _extract_block_text(page: fitz.Page, rect: fitz.Rect) -> str:
    """Return the text rendered inside ``rect`` on ``page`` in reading order."""
    words = page.get_text("words", clip=rect)
    return " ".join(word[4] for word in words)


def _block_union_rect(block: _Block) -> fitz.Rect:
    """Return the tight bounding box of every span in ``block``."""
    rect = fitz.Rect()
    for span in block.spans:
        rect |= span.rect
    return rect


def _rects_overlap(a: fitz.Rect, b: fitz.Rect) -> bool:
    """Return True when two rectangles genuinely intersect.

    Touching edges (where one rect ends exactly where another begins) are NOT
    considered overlaps -- only a positive intersection area fails.
    """
    return a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1


def _rect_contains(outer: fitz.Rect, inner: fitz.Rect) -> bool:
    """Return True when ``outer`` fully contains ``inner``."""
    return (
        outer.x0 <= inner.x0
        and outer.y0 <= inner.y0
        and outer.x1 >= inner.x1
        and outer.y1 >= inner.y1
    )


def _fill_rgb(fill) -> tuple[float, float, float] | None:
    """Return a solid RGB fill as floats in 0..1, or None if unsupported."""
    if fill is None:
        return None
    try:
        values = [float(value) for value in fill]
    except (TypeError, ValueError):
        return None
    if len(values) == 1:
        values = values * 3
    if len(values) != 3:
        return None
    if any(value < 0.0 or value > 1.0 for value in values):
        return None
    return (values[0], values[1], values[2])


def _drawing_fill_is_white(fill) -> bool:
    """Return True when a drawing fill is white or absent."""
    rgb = _fill_rgb(fill)
    return rgb is None or all(component >= 0.99 for component in rgb)


def _background_color(
    page: fitz.Page, rect: fitz.Rect
) -> tuple[tuple[float, float, float] | None, str | None]:
    """Return the detected background colour for ``rect``.

    Raster images are always rejected. Solid vector fills that fully cover the
    block are accepted, using the topmost fill. Partially covering fills,
    translucent fills, malformed colours and unsupported drawings are rejected
    as uncertain rather than guessed.
    """
    try:
        image_info = page.get_image_info()
    except Exception:
        return None, "uncertain_background"

    for info in image_info:
        bbox = info.get("bbox")
        if not bbox or len(bbox) != 4:
            return None, "uncertain_background"
        try:
            image_rect = fitz.Rect(bbox)
        except Exception:
            return None, "uncertain_background"
        if image_rect.width <= 0 or image_rect.height <= 0:
            continue
        if _rects_overlap(image_rect, rect):
            return None, "raster_image"

    try:
        drawings = page.get_drawings()
    except Exception:
        return None, "uncertain_background"

    background: tuple[float, float, float] | None = None
    for drawing in drawings:
        raw_rect = drawing.get("rect")
        if raw_rect is None:
            continue
        try:
            draw_rect = fitz.Rect(raw_rect)
        except Exception:
            return None, "uncertain_background"
        if not _rects_overlap(draw_rect, rect):
            continue
        if any(item and item[0] == "i" for item in drawing.get("items", [])):
            return None, "raster_image"
        fill = drawing.get("fill")
        if fill is None:
            continue
        if not _rect_contains(draw_rect, rect):
            return None, "uncertain_background"
        opacity = drawing.get("fill_opacity")
        if opacity is not None and float(opacity) < 0.99:
            return None, "uncertain_background"
        rgb = _fill_rgb(fill)
        if rgb is None:
            return None, "uncertain_background"
        background = rgb

    return background or (1.0, 1.0, 1.0), None


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    """Return WCAG relative luminance for an RGB colour in 0..1."""

    def linearize(component: float) -> float:
        if component <= 0.04045:
            return component / 12.92
        return ((component + 0.055) / 1.055) ** 2.4

    red, green, blue = (linearize(component) for component in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> float:
    """Return the WCAG contrast ratio between two RGB colours."""
    first_luminance = _relative_luminance(first)
    second_luminance = _relative_luminance(second)
    lighter = max(first_luminance, second_luminance)
    darker = min(first_luminance, second_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def _span_color_rgb(color: int) -> tuple[float, float, float]:
    """Convert PyMuPDF's packed sRGB integer to an RGB tuple."""
    return (
        ((color >> 16) & 0xFF) / 255.0,
        ((color >> 8) & 0xFF) / 255.0,
        (color & 0xFF) / 255.0,
    )


def _is_large_text(block: _Block) -> bool:
    """Return True when every span qualifies as large text for WCAG contrast."""
    if not block.spans:
        return block.font_size >= 18.0
    for span in block.spans:
        bold = bool(span.flags & 16)
        if span.size >= 18.0:
            continue
        if bold and span.size >= 14.0:
            continue
        return False
    return True


def _choose_text_color(
    block: _Block, background: tuple[float, float, float]
) -> tuple[tuple[float, float, float] | None, str | None]:
    """Choose an adequate text colour for the detected background.

    The original colour is used only when every original span colour meets the
    applicable WCAG threshold. Otherwise black or white is chosen only when it
    meets the threshold; otherwise the block is rejected.
    """
    threshold = LARGE_TEXT_CONTRAST if _is_large_text(block) else NORMAL_TEXT_CONTRAST
    weights: dict[int, int] = {}
    for span in block.spans:
        weights[span.color] = weights.get(span.color, 0) + max(1, len(span.text))
    if not weights:
        weights[0] = 1

    ratios = {
        color: _contrast_ratio(_span_color_rgb(color), background)
        for color in weights
    }
    if min(ratios.values()) >= threshold:
        dominant = max(weights, key=lambda color: (weights[color], -color))
        return _span_color_rgb(dominant), None

    black = (0.0, 0.0, 0.0)
    white = (1.0, 1.0, 1.0)
    black_ratio = _contrast_ratio(black, background)
    white_ratio = _contrast_ratio(white, background)
    if black_ratio >= white_ratio and black_ratio >= threshold:
        return black, None
    if white_ratio > black_ratio and white_ratio >= threshold:
        return white, None
    return None, "insufficient_contrast"


def _minimum_font_size(original: float) -> float:
    """Return the approved minimum font size for an original size."""
    if original < MIN_FONT_SIZE:
        return original
    return round(max(MIN_FONT_SIZE, original * MAX_FONT_SHRINK_RATIO), 2)


def _font_size_candidates(original: float) -> list[float]:
    """Return descending font sizes from the original down to the policy floor."""
    original = max(1.0, float(original))
    minimum = _minimum_font_size(original)
    if original <= minimum + 0.001:
        return [round(original, 2)]

    sizes: list[float] = []
    size = original
    while size > minimum + 0.001:
        sizes.append(round(size, 2))
        size -= 0.5
    sizes.append(round(minimum, 2))
    return sizes


def _redaction_rect(block: _Block) -> fitz.Rect:
    """Return the text block rectangle with a small redaction safety margin."""
    rect = _block_union_rect(block)
    return fitz.Rect(
        rect.x0 - REDACTION_PADDING,
        rect.y0 - REDACTION_PADDING,
        rect.x1 + REDACTION_PADDING,
        rect.y1 + REDACTION_PADDING,
    )


def _overlay_block(
    page: fitz.Page,
    block_index: int,
    block: _Block,
    translated: str,
    fontname: str,
    font_path: str | None,
    rtl: bool,
    text_color: tuple[float, float, float],
) -> OverflowBlock | None:
    """Insert one translated block into its original geometry.

    Returns ``None`` on success or an ``OverflowBlock`` describing the failure.
    The caller must fail the job when any overflow is returned.
    """
    rect = _block_union_rect(block)
    align = fitz.TEXT_ALIGN_RIGHT if rtl else fitz.TEXT_ALIGN_LEFT
    for size in _font_size_candidates(block.font_size):
        result = page.insert_textbox(
            rect,
            translated,
            fontsize=size,
            fontname=fontname,
            fontfile=font_path,
            align=align,
            color=text_color,
        )
        if result >= 0:
            return None

    return OverflowBlock(
        page=page.number,
        block=block_index,
        rect=list(rect),
        text=translated,
        font_size=_minimum_font_size(block.font_size),
        reason="exceeds_min_font",
    )


def _overflow_message(overflow: OverflowBlock) -> str:
    """Return a safe user-facing message for an overlay failure."""
    page_number = overflow.page + 1
    if overflow.reason == "raster_image":
        detail = "contains text over an image, which cannot be translated safely."
    elif overflow.reason == "uncertain_background":
        detail = (
            "contains text over a background that cannot be identified safely."
        )
    elif overflow.reason == "insufficient_contrast":
        detail = "has no text colour with adequate contrast against its background."
    else:
        detail = "has translated text that does not fit in the original layout."
    return f"Page {page_number} {detail}"


def _overlay_pdf(
    clone: fitz.Document,
    pages: list[_Page],
    translations: list[str],
    output_path: Path,
    font_path: str | None,
    rtl: bool,
) -> None:
    """Redact source text, overlay translations, and validate the saved PDF."""
    if clone.page_count != len(pages):
        raise DocumentProcessingError(
            "The PDF page structure changed unexpectedly and cannot be translated."
        )

    fontname = "F0" if font_path else "helv"

    try:
        cursor = 0
        for page_index, page in enumerate(clone):
            source_page = pages[page_index]
            pending: list[
                tuple[
                    int,
                    _Block,
                    str,
                    fitz.Rect,
                    fitz.Rect,
                    tuple[float, float, float],
                ]
            ] = []
            redaction_rects: list[fitz.Rect] = []

            for block_index, block in enumerate(source_page.blocks):
                translated = translations[cursor]
                cursor += 1
                if not _normalize_text(translated):
                    raise DocumentProcessingError(
                        f"Page {page.number + 1} contains an empty translation, "
                        "so the PDF was not written."
                    )

                rect = _block_union_rect(block)
                redaction_rect = _redaction_rect(block)
                redaction_rects.append(redaction_rect)

                background, background_reason = _background_color(page, rect)
                if background is None:
                    overflow = OverflowBlock(
                        page=page.number,
                        block=block_index,
                        rect=list(rect),
                        text=translated,
                        font_size=block.font_size,
                        reason=background_reason or "uncertain_background",
                    )
                    raise DocumentProcessingError(_overflow_message(overflow))

                text_color, color_reason = _choose_text_color(block, background)
                if text_color is None:
                    overflow = OverflowBlock(
                        page=page.number,
                        block=block_index,
                        rect=list(rect),
                        text=translated,
                        font_size=block.font_size,
                        reason=color_reason or "insufficient_contrast",
                    )
                    raise DocumentProcessingError(_overflow_message(overflow))

                pending.append(
                    (
                        block_index,
                        block,
                        translated,
                        rect,
                        redaction_rect,
                        text_color,
                    )
                )

                for i in range(len(redaction_rects)):
                    for j in range(i + 1, len(redaction_rects)):
                        if _rects_overlap(redaction_rects[i], redaction_rects[j]):
                            raise DocumentProcessingError(
                                "The PDF layout is not supported: overlapping text blocks "
                                "were detected."
                            )

                if not pending:
                    continue

                for _, _, _, _, redaction_rect, _ in pending:
                    page.add_redact_annot(redaction_rect, fill=None)

                applied = page.apply_redactions(
                    images=fitz.PDF_REDACT_IMAGE_NONE,
                    graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                    text=fitz.PDF_REDACT_TEXT_REMOVE,
                )
                if not applied:
                    raise DocumentProcessingError(
                        f"Page {page.number + 1} could not be redacted safely."
                    )

                for _, _, _, _, redaction_rect, _ in pending:
                    remaining = _extract_block_text(page, redaction_rect)
                    if _normalize_text(remaining):
                        raise DocumentProcessingError(
                            f"Original text could not be removed safely on page "
                            f"{page.number + 1}."
                        )

                if font_path:
                    page.insert_font(fontname=fontname, fontfile=font_path)

                for block_index, block, translated, _, _, text_color in pending:
                    overflow = _overlay_block(
                        page,
                        block_index,
                        block,
                        translated,
                        fontname,
                        font_path,
                        rtl,
                        text_color,
                    )
                    if overflow is not None:
                        raise DocumentProcessingError(_overflow_message(overflow))

        clone.save(str(output_path), garbage=3, deflate=True)

        validated = fitz.open(str(output_path))
        try:
            if validated.page_count != len(pages):
                raise DocumentProcessingError(
                    "The translated PDF page count does not match the source."
                )
            cursor = 0
            for page in validated:
                source_page = pages[page.number]
                if (
                    abs(page.rect.width - source_page.width) > 0.01
                    or abs(page.rect.height - source_page.height) > 0.01
                ):
                    raise DocumentProcessingError(
                        "The translated PDF page dimensions changed unexpectedly."
                    )
                for block in source_page.blocks:
                    rect = _block_union_rect(block)
                    rendered = _extract_block_text(page, rect)
                    if not _validate_block(translations[cursor], rendered):
                        raise DocumentProcessingError(
                            "The translated text was not rendered correctly in the "
                            "saved PDF."
                        )
                    cursor += 1
        finally:
            validated.close()
    except Exception:
        _remove_partial_output(output_path)
        raise


def _remove_partial_output(path: Path) -> None:
    """Remove a partially written output file without masking the real error."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove partial PDF output at %s", path)


def _extract_pages(document: fitz.Document) -> list[_Page]:
    pages: list[_Page] = []
    for page in document:
        raw = page.get_text("dict", sort=True)
        blocks: list[_Block] = []
        # Column state accumulated across PyMuPDF blocks within the page.
        # PyMuPDF groups side-by-side columns by row, so a multi-row column
        # spans several consecutive blocks; we merge them here.
        active_columns: list[list[list[_Span]]] = []
        col_x0: list[float] = []
        col_x1: list[float] = []
        col_max_size: list[float] = []
        active_sizes: list[float] = []
        last_block_y1: float | None = None
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            line_groups: list[list[list[_Span]]] = []
            sizes: list[float] = []
            for line in block.get("lines", []):
                line_spans: list[_Span] = []
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    bbox = span.get("bbox")
                    if not bbox or len(bbox) != 4:
                        continue
                    rect = fitz.Rect(bbox)
                    if rect.width <= 0 or rect.height <= 0:
                        continue
                    size = float(span.get("size", 10.0))
                    color = int(span.get("color", 0) or 0)
                    font_name = str(span.get("font", "helv"))
                    flags = int(span.get("flags", 0) or 0)
                    line_spans.append(
                        _Span(
                            text=text,
                            rect=rect,
                            size=size,
                            color=color,
                            font=font_name,
                            flags=flags,
                        )
                    )
                    sizes.append(size)
                line_groups.append(_split_columns(line_spans))

            if not line_groups:
                continue

            # When every line splits into the same number of column groups,
            # emit one logical block per column so columns are separated.
            group_counts = {len(groups) for groups in line_groups}
            split_into_columns = len(group_counts) == 1 and max(group_counts) > 1

            # A "row pair" block: several single-span lines sitting side by
            # side on the same baseline (PyMuPDF groups them into one block).
            # These belong to the multi-row columns we are accumulating.
            non_empty = [groups for groups in line_groups if groups and groups[0]]
            is_row_pair = (
                not split_into_columns
                and len(non_empty) >= 2
                and all(len(groups) == 1 for groups in non_empty)
            )

            if is_row_pair:
                for groups in non_empty:
                    group = groups[0]
                    x0 = group[0].rect.x0
                    x1 = max(s.rect.x1 for s in group)
                    group_size = max(s.size for s in group)
                    assigned = False
                    for idx in range(len(active_columns)):
                        # Use the smaller of the two sides' font sizes as the
                        # reference, so a big heading in one column cannot
                        # inflate the tolerance enough to swallow a narrow
                        # adjacent column with small body text. A space is
                        # roughly a quarter of the font size, so the smaller
                        # font is the stricter (and safer) reference.
                        ref_size = min(group_size, col_max_size[idx])
                        gap_tol = 3.0 * ref_size
                        gap_right = x0 - col_x1[idx]
                        gap_left = col_x0[idx] - x1
                        if gap_right <= gap_tol and gap_left <= gap_tol:
                            active_columns[idx].append(group)
                            col_x0[idx] = min(col_x0[idx], x0)
                            col_x1[idx] = max(col_x1[idx], x1)
                            col_max_size[idx] = max(col_max_size[idx], group_size)
                            assigned = True
                            break
                    if not assigned:
                        active_columns.append([group])
                        col_x0.append(x0)
                        col_x1.append(x1)
                        col_max_size.append(group_size)
                active_sizes.extend(sizes)
                block_rects = [
                    s.rect for groups in non_empty for g in groups for s in g
                ]
                last_block_y1 = max(r.y1 for r in block_rects)
                continue

            # A non-row-pair block ends any multi-row column sequence that was
            # being accumulated, provided it sits below the columns (a gap in
            # reading order) or the columns have already been flushed.
            if active_columns and last_block_y1 is not None:
                first_y0 = min(
                    s.rect.y0 for groups in non_empty for g in groups for s in g
                )
                if first_y0 >= last_block_y1:
                    _flush_columns(active_columns, col_x0, active_sizes, blocks)
                    active_columns = []
                    col_x0 = []
                    col_x1 = []
                    col_max_size = []
                    active_sizes = []
                    last_block_y1 = None

            if not split_into_columns:
                spans: list[_Span] = []
                line_texts: list[str] = []
                for groups in line_groups:
                    for group in groups:
                        parts: list[str] = []
                        for i, span in enumerate(group):
                            if i > 0 and _span_gap_is_space(group[i - 1], span):
                                parts.append(" ")
                            parts.append(span.text)
                        if parts:
                            line_texts.append("".join(parts))
                            spans.extend(group)
                if not spans:
                    continue
                text = " ".join(line_texts)
                size = median(sizes) if sizes else 10.0
                size = max(1.0, size)
                blocks.append(_Block(text=text, font_size=size, spans=spans))
                continue

            num_columns = max(group_counts)
            for col in range(num_columns):
                spans = [span for groups in line_groups for span in groups[col]]
                if not spans:
                    continue
                line_texts = []
                for groups in line_groups:
                    group = groups[col]
                    parts = []
                    for i, span in enumerate(group):
                        if i > 0 and _span_gap_is_space(group[i - 1], span):
                            parts.append(" ")
                        parts.append(span.text)
                    if parts:
                        line_texts.append("".join(parts))
                text = " ".join(line_texts)
                size = median(sizes) if sizes else 10.0
                size = max(1.0, size)
                blocks.append(_Block(text=text, font_size=size, spans=spans))

        # Flush any columns still active at the end of the page.
        if active_columns:
            _flush_columns(active_columns, col_x0, active_sizes, blocks)

        pages.append(_Page(width=page.rect.width, height=page.rect.height, blocks=blocks))
    return pages
