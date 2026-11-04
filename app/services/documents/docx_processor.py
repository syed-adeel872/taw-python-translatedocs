"""DOCX translation that preserves styles, tables and run formatting.

Strategy: each paragraph (body, table cell, header, footer) is collected once.
Paragraphs with multiple formatted runs are translated as one segment containing
stable run markers. The translated pieces are mapped back to the same original
runs, preserving bold/italic/colour/font formatting without proportional
redistribution. If a provider does not preserve the markers, the paragraph is
retranslated segment by segment and a warning is recorded.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from app.errors import CorruptedDocumentError, DocumentProcessingError, EmptyDocumentError
from app.services.documents.base import ProcessResult
from app.services.translation.base import TranslationService

logger = logging.getLogger(__name__)

_MARKER_FRAGMENT = "[[[R"
_MARKER_PATTERN = re.compile(r"\[\[\[R(\d+)\]\]\](.*?)\[\[\[/R\1\]\]\]", re.DOTALL)

DOCX_WARNINGS = [
    "DOCX structure, headings, tables and run formatting (bold, italic, colour, "
    "font) are preserved.",
    "Translated text is mapped back to the original formatted runs with stable "
    "segment markers. If a provider cannot preserve the markers, the paragraph "
    "is translated segment by segment and the job records a warning; text is "
    "never redistributed proportionally.",
    "Inline images, charts, text boxes and hyperlinks are kept in the file; text "
    "inside those objects is not translated. Objects that share a run with "
    "translated text are preserved, but their position may shift.",
    "Footnotes, comments and tracked changes are left untouched.",
    "Complex layouts and line breaks inside a paragraph may shift slightly.",
]


@dataclass
class _ParagraphPlan:
    paragraph: Paragraph
    runs: list
    piece_runs: list[int]
    piece_texts: list[str]
    source_text: str
    marked_text: str
    leading: str
    trailing: str
    use_markers: bool


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

        plans: list[_ParagraphPlan] = []
        for paragraph in _iter_unique_paragraphs(document):
            plan = _plan_paragraph(paragraph)
            if plan is not None:
                plans.append(plan)

        if not plans:
            raise EmptyDocumentError(
                "The DOCX document contains no translatable text."
            )

        translations = self.translator.translate_texts(
            [plan.marked_text for plan in plans], source_language, target_language
        )

        fallback_count = 0
        shifted_object_count = 0
        for plan, translated in zip(plans, translations):
            if plan.use_markers:
                pieces = _parse_marked_translation(translated, len(plan.piece_runs))
                if pieces is None:
                    shifted_object_count += self._translate_per_run(
                        plan, source_language, target_language
                    )
                    fallback_count += 1
                else:
                    shifted_object_count += _assign_pieces(plan, pieces)
            elif len(plan.piece_runs) == 1:
                shifted_object_count += _assign_pieces(plan, [translated])
            else:
                shifted_object_count += self._translate_per_run(
                    plan, source_language, target_language
                )
                fallback_count += 1

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            document.save(str(output_path))
        except Exception as exc:
            raise DocumentProcessingError(
                "The translated DOCX file could not be generated."
            ) from exc

        warnings = list(DOCX_WARNINGS)
        if fallback_count:
            logger.warning(
                "DOCX provider markers were unusable for %s paragraph(s); "
                "used segment-by-segment translation instead.",
                fallback_count,
            )
            warnings.append(
                f"{fallback_count} paragraph(s) used segment-by-segment "
                "translation because the provider did not preserve the formatting "
                "markers."
            )

        if shifted_object_count:
            warnings.append(
                f"{shifted_object_count} run(s) contained non-text content "
                "alongside translated text; the content was preserved, but its "
                "position may have shifted."
            )

        return ProcessResult(
            characters=sum(len(plan.source_text) for plan in plans),
            segments=len(plans),
            warnings=warnings,
        )

    def _translate_per_run(
        self,
        plan: _ParagraphPlan,
        source_language: str,
        target_language: str,
    ) -> int:
        pieces = self.translator.translate_texts(
            plan.piece_texts, source_language, target_language
        )
        if len(pieces) != len(plan.piece_runs):
            raise DocumentProcessingError(
                "The translated DOCX text could not be mapped back to its "
                "original formatting."
            )
        return _assign_pieces(plan, pieces)


def _plan_paragraph(paragraph: Paragraph) -> _ParagraphPlan | None:
    runs = list(paragraph.runs)
    full_text = "".join(run.text for run in runs)
    if not full_text.strip():
        return None
    if not any(character.isalpha() for character in full_text):
        return None

    leading = full_text[: len(full_text) - len(full_text.lstrip())]
    trailing = full_text[len(full_text.rstrip()) :]

    pieces = [(index, run.text) for index, run in enumerate(runs) if run.text]
    if not pieces:
        return None

    if len(pieces) == 1:
        index, text = pieces[0]
        pieces[0] = (index, text.strip())
    else:
        first_index, first_text = pieces[0]
        pieces[0] = (first_index, first_text.lstrip())
        last_index, last_text = pieces[-1]
        pieces[-1] = (last_index, last_text.rstrip())
    pieces = [(index, text) for index, text in pieces if text]
    if not pieces:
        return None

    source_text = "".join(text for _, text in pieces)
    use_markers = len(pieces) > 1 and not any(
        _MARKER_FRAGMENT in text for _, text in pieces
    )
    if use_markers:
        marked_text = "".join(
            f"[[[R{position}]]]{text}[[[/R{position}]]]"
            for position, (_, text) in enumerate(pieces)
        )
    else:
        marked_text = source_text

    return _ParagraphPlan(
        paragraph=paragraph,
        runs=runs,
        piece_runs=[index for index, _ in pieces],
        piece_texts=[text for _, text in pieces],
        source_text=source_text,
        marked_text=marked_text,
        leading=leading,
        trailing=trailing,
        use_markers=use_markers,
    )


def _parse_marked_translation(text: str, expected: int) -> list[str] | None:
    matches = list(_MARKER_PATTERN.finditer(text))
    if len(matches) != expected:
        return None

    pieces: list[str] = []
    cursor = 0
    for position, match in enumerate(matches):
        if match.start() != cursor and text[cursor : match.start()].strip():
            return None
        if int(match.group(1)) != position:
            return None
        piece = match.group(2)
        if not piece.strip():
            return None
        pieces.append(piece)
        cursor = match.end()

    if text[cursor:].strip():
        return None
    return pieces


_LAYOUT_CONTENT_TAGS = frozenset({qn("w:lastRenderedPageBreak")})


def _is_text_run_child(element) -> bool:
    """Return True for run children that represent translatable text content.

    Plain line breaks (``w:br`` without an explicit page/column type) are
    text content because they round-trip through ``\\n``.  Breaks that carry a
    page or column type are document objects and must be preserved verbatim.
    """
    tag = element.tag
    if tag in (qn("w:t"), qn("w:tab"), qn("w:cr"), qn("w:noBreakHyphen"), qn("w:ptab")):
        return True
    if tag == qn("w:br"):
        break_type = element.get(qn("w:type"))
        return break_type in (None, "", "textWrapping")
    return False


def _run_has_non_text_content(run) -> bool:
    """Return True when a run contains content other than properties or text."""
    return any(
        not _is_text_run_child(child)
        and child.tag != qn("w:rPr")
        for child in run._r
    )


def _new_text_elements(text: str) -> list:
    """Return WordprocessingML elements for text without clearing the run."""
    elements: list = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        chunk = "".join(buffer)
        element = OxmlElement("w:t")
        element.text = chunk
        if len(chunk.strip()) < len(chunk):
            element.set(qn("xml:space"), "preserve")
        elements.append(element)
        buffer.clear()

    for character in text:
        if character == "\t":
            flush()
            elements.append(OxmlElement("w:tab"))
        elif character in "\r\n":
            flush()
            elements.append(OxmlElement("w:br"))
        else:
            buffer.append(character)
    flush()
    return elements


def _replace_run_text(run, text: str) -> bool:
    """Replace run text while preserving non-text children.

    Returns True when the run contained reportable non-text content.
    """
    if not _run_has_non_text_content(run):
        run.text = text
        return False

    children = list(run._r)
    text_positions = [
        index for index, child in enumerate(children) if _is_text_run_child(child)
    ]
    insert_at = text_positions[0] if text_positions else len(children)
    for child in children:
        if _is_text_run_child(child):
            run._r.remove(child)

    for offset, element in enumerate(_new_text_elements(text)):
        run._r.insert(insert_at + offset, element)

    return any(
        not _is_text_run_child(child)
        and child.tag not in _LAYOUT_CONTENT_TAGS
        and child.tag != qn("w:rPr")
        for child in children
    )


def _assign_pieces(plan: _ParagraphPlan, pieces: list[str]) -> int:
    if len(pieces) != len(plan.piece_runs):
        raise DocumentProcessingError(
            "The translated DOCX text could not be mapped back to its original "
            "formatting."
        )

    shifted_object_count = 0
    last_position = len(pieces) - 1
    for position, (run_index, piece) in enumerate(zip(plan.piece_runs, pieces)):
        source = plan.piece_texts[position]
        leading_space = source[: len(source) - len(source.lstrip())]
        trailing_space = source[len(source.rstrip()) :]
        if leading_space and not piece[:1].isspace():
            piece = f"{leading_space}{piece}"
        if trailing_space and not piece[-1:].isspace():
            piece = f"{piece}{trailing_space}"
        if position == 0:
            piece = f"{plan.leading}{piece}"
        if position == last_position:
            piece = f"{piece}{plan.trailing}"
        if _replace_run_text(plan.runs[run_index], piece):
            shifted_object_count += 1
    return shifted_object_count


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
