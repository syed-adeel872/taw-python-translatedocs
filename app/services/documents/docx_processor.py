"""DOCX translation that preserves styles, tables and run formatting.

Strategy: each paragraph (body, table cell, header, footer) is collected once.
The paragraph text is translated as one segment, then redistributed across the
original runs in proportion to their source lengths. This keeps run-level
formatting (bold/italic/colour/font) attached to approximately the same part of
the text and leaves paragraph and table structure untouched.
"""

from __future__ import annotations

import logging
from pathlib import Path

from docx import Document
from docx.text.paragraph import Paragraph

from app.errors import CorruptedDocumentError, DocumentProcessingError, EmptyDocumentError
from app.services.documents.base import ProcessResult
from app.services.translation.base import TranslationService

logger = logging.getLogger(__name__)

DOCX_WARNINGS = [
    "DOCX structure, headings, tables and basic run formatting (bold, italic, "
    "colour, font) are preserved.",
    "Run-level formatting properties survive translation, but the translated "
    "text is redistributed proportionally across the original runs. A "
    "shorter translation can leave an originally formatted run empty, so the "
    "translated text may no longer appear with its original formatting.",
    "Images, charts, text boxes, footnotes, comments and tracked changes are kept "
    "in the file but their text is not translated.",
    "Complex layouts and line breaks inside a paragraph may shift slightly.",
]


class DocxProcessor:
    def __init__(self, translator: TranslationService) -> None:
        self.translator = translator

    def process(
        self,
        input_path: Path,
        output_path: Path,
        source_language: str,
        target_language: str,
    ) -> ProcessResult:
        try:
            document = Document(str(input_path))
        except Exception as exc:
            raise CorruptedDocumentError(
                "The DOCX file could not be opened. It may be corrupted."
            ) from exc

        entries: list[tuple[Paragraph, str, str, str]] = []
        for paragraph in _iter_unique_paragraphs(document):
            full_text = "".join(run.text for run in paragraph.runs)
            if not full_text.strip():
                continue
            if not any(character.isalpha() for character in full_text):
                continue

            stripped = full_text.strip()
            leading = full_text[: len(full_text) - len(full_text.lstrip())]
            trailing = full_text[len(full_text.rstrip()) :]
            entries.append((paragraph, stripped, leading, trailing))

        if not entries:
            raise EmptyDocumentError(
                "The DOCX document contains no translatable text."
            )

        texts = [entry[1] for entry in entries]
        translations = self.translator.translate_texts(
            texts, source_language, target_language
        )

        for (paragraph, _source, leading, trailing), translated in zip(
            entries, translations
        ):
            _rewrite_paragraph(paragraph, f"{leading}{translated}{trailing}")

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            document.save(str(output_path))
        except Exception as exc:
            raise DocumentProcessingError(
                "The translated DOCX file could not be generated."
            ) from exc

        return ProcessResult(
            characters=sum(len(text) for text in texts),
            segments=len(entries),
            warnings=list(DOCX_WARNINGS),
        )


def _iter_unique_paragraphs(document):  # type: ignore[no-untyped-def]
    seen: set[tuple[str, str]] = set()

    def paragraph_key(paragraph: Paragraph) -> tuple[str, str]:
        try:
            part_name = str(paragraph.part.partname)
        except Exception:
            part_name = ""
        try:
            path = paragraph._p.getroottree().getpath(paragraph._p)
        except Exception:
            path = str(id(paragraph._p))
        return part_name, path

    def visit(paragraph: Paragraph):
        key = paragraph_key(paragraph)
        if key in seen:
            return
        seen.add(key)
        yield paragraph

    def visit_table(table):
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    yield from visit(paragraph)
                for nested in cell.tables:
                    yield from visit_table(nested)

    for paragraph in document.paragraphs:
        yield from visit(paragraph)
    for table in document.tables:
        yield from visit_table(table)

    for section in document.sections:
        for container in (
            section.header,
            section.footer,
            section.first_page_header,
            section.first_page_footer,
            section.even_page_header,
            section.even_page_footer,
        ):
            for paragraph in container.paragraphs:
                yield from visit(paragraph)
            for table in container.tables:
                yield from visit_table(table)


def _rewrite_paragraph(paragraph: Paragraph, translated: str) -> None:
    runs = list(paragraph.runs)
    if not runs:
        paragraph.add_run(translated)
        return

    lengths = [len(run.text) for run in runs]
    total = sum(lengths)

    if total == 0:
        runs[0].text = translated
        for run in runs[1:]:
            run.text = ""
        return

    non_empty = [index for index, length in enumerate(lengths) if length > 0]
    if len(non_empty) == 1:
        target = non_empty[0]
        for index, run in enumerate(runs):
            run.text = translated if index == target else ""
        return

    for run, piece in zip(runs, _distribute_text(translated, lengths)):
        run.text = piece


def _distribute_text(text: str, lengths: list[int]) -> list[str]:
    total = sum(lengths)
    if total <= 0:
        pieces = ["" for _ in lengths]
        pieces[0] = text
        return pieces

    pieces: list[str] = []
    previous = 0
    cumulative = 0

    for length in lengths[:-1]:
        cumulative += length
        target = round(len(text) * cumulative / total)
        target = _snap_to_space(text, target, previous)
        target = max(previous, min(target, len(text)))
        pieces.append(text[previous:target])
        previous = target

    pieces.append(text[previous:])
    return pieces


def _snap_to_space(text: str, target: int, lower_bound: int) -> int:
    upper_bound = len(text)
    if target <= lower_bound or target >= upper_bound:
        return target

    window = max(4, min(15, (upper_bound - lower_bound) // 4))
    for offset in range(window + 1):
        for candidate in (target - offset, target + offset):
            if lower_bound < candidate < upper_bound and text[candidate - 1] in " \t":
                return candidate
    return target
