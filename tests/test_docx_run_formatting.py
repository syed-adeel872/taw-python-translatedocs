"""Focused regression tests for DOCX run-level formatting association.

These tests separate two claims:

* *property preservation* -- the ``<w:i/>`` / ``<w:b/>`` element survives on its
  run after the processor rewrites the run text?
* *text-to-formatting association* -- does translated text stay attached to the
  same run whose source text it replaces?

Marker-preserving providers must keep association without any proportional
redistribution. Providers that ignore or damage markers trigger the documented
segment-by-segment fallback, which still keeps each translated piece on its
original run and records a warning.
"""

from __future__ import annotations

import base64
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches

from app.services.documents.docx_processor import DocxProcessor, _parse_marked_translation
from app.services.translation.base import TranslationProvider, TranslationService
from app.services.translation.mock import MockTranslationProvider

_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAusB9Wl2nGQAAAAASUVORK5CYII="
)


class PrefixProvider(TranslationProvider):
    """Mimics the mock provider: prefix the target language code."""

    name = "prefix"

    def translate(self, texts, source_language, target_language):
        return [f"[{target_language}] {text}" for text in texts]


class ShortProvider(TranslationProvider):
    """Return a translation strictly shorter than the source paragraph."""

    name = "short"

    def translate(self, texts, source_language, target_language):
        return ["X"] * len(texts)


def _process_with_result(
    document: Document, provider: TranslationProvider, tmp_path: Path
):
    src = tmp_path / "in.docx"
    out = tmp_path / "out.docx"
    document.save(str(src))
    result = DocxProcessor(
        TranslationService(provider, max_retries=0, retry_backoff=0)
    ).process(src, out, "auto", "es")
    return Document(str(out)), result


def _process(document: Document, provider: TranslationProvider, tmp_path: Path) -> Document:
    return _process_with_result(document, provider, tmp_path)[0]


def _write_png(tmp_path: Path) -> Path:
    image_path = tmp_path / "inline.png"
    image_path.write_bytes(_PNG_BYTES)
    return image_path


def _assert_png_relationship(document: Document) -> None:
    assert len(document.inline_shapes) == 1
    inline = document.inline_shapes[0]._inline
    relationship_id = inline.graphic.graphicData.pic.blipFill.blip.embed
    assert relationship_id
    assert relationship_id in document.part.related_parts
    image_part = document.part.related_parts[relationship_id]
    assert image_part.content_type == "image/png"
    assert image_part.blob == _PNG_BYTES


def _mixed_paragraph(document: Document) -> None:
    """Plain "The " + italic "word" + plain " is here" (16 source chars)."""
    paragraph = document.add_paragraph()
    paragraph.add_run("The ")
    italic = paragraph.add_run("word")
    italic.italic = True
    paragraph.add_run(" is here")


def test_marker_mapping_preserves_text_to_formatting_association(tmp_path):
    """Each translated piece stays on the run that held its source text."""
    document = Document()
    paragraph = document.add_paragraph()
    bold = paragraph.add_run("Bold product name")
    bold.bold = True
    paragraph.add_run(" and ")
    italic = paragraph.add_run("italic note")
    italic.italic = True

    result = _process(document, MockTranslationProvider(), tmp_path)
    body = result.paragraphs[0]

    assert body.runs[0].bold
    assert body.runs[0].text == "[es] Bold product name"
    assert body.runs[1].text == " and "
    assert body.runs[2].italic
    assert body.runs[2].text == "italic note"
    assert body.text == "[es] Bold product name and italic note"


def test_short_translation_falls_back_and_keeps_each_run_populated(tmp_path):
    """A provider that discards markers triggers per-run translation."""
    document = Document()
    _mixed_paragraph(document)

    output, result = _process_with_result(document, ShortProvider(), tmp_path)
    body = output.paragraphs[0]

    italic_runs = [run for run in body.runs if run.italic]
    assert italic_runs
    assert italic_runs[0].text == "X"
    assert all(run.text for run in body.runs if run.text)
    assert any(
        "segment-by-segment" in warning for warning in result.warnings
    ), result.warnings


def test_mixed_bold_and_italic_runs_keep_their_translated_text(tmp_path):
    """The fallback keeps bold and italic runs populated instead of emptying them."""
    document = Document()
    paragraph = document.add_paragraph()
    bold_a = paragraph.add_run("The ")
    bold_a.bold = True
    italic_b = paragraph.add_run("word")
    italic_b.italic = True
    paragraph.add_run(" is here")

    output, _ = _process_with_result(document, ShortProvider(), tmp_path)
    body = output.paragraphs[0]

    bold_runs = [run for run in body.runs if run.bold]
    italic_runs = [run for run in body.runs if run.italic]
    assert bold_runs and bold_runs[0].text == "X "
    assert italic_runs and italic_runs[0].text == "X"
    assert body.text == "X X X"


def test_inline_image_in_translatable_paragraph_is_preserved(tmp_path):
    image_path = _write_png(tmp_path)
    document = Document()
    paragraph = document.add_paragraph()
    bold = paragraph.add_run("Before image ")
    bold.bold = True
    paragraph.add_run().add_picture(str(image_path), width=Inches(0.5))
    italic = paragraph.add_run(" after image")
    italic.italic = True

    output, result = _process_with_result(
        document, MockTranslationProvider(), tmp_path
    )
    body = output.paragraphs[0]

    assert len(output.inline_shapes) == 1
    assert body.runs[0].bold
    assert body.runs[0].text == "[es] Before image "
    assert body.runs[1]._r.xpath(".//w:drawing")
    assert body.runs[2].italic
    assert body.runs[2].text == " after image"
    assert not any("non-text content" in warning for warning in result.warnings)
    _assert_png_relationship(output)


def test_inline_image_sharing_a_text_run_is_preserved_with_warning(tmp_path):
    image_path = _write_png(tmp_path)
    document = Document()
    paragraph = document.add_paragraph()
    run = paragraph.add_run()
    run.bold = True
    run.add_picture(str(image_path), width=Inches(0.5))
    run.add_text(" caption")

    output, result = _process_with_result(
        document, MockTranslationProvider(), tmp_path
    )
    body = output.paragraphs[0]

    assert len(output.inline_shapes) == 1
    assert body.runs[0].bold
    assert "caption" in body.runs[0].text
    assert any("non-text content" in warning for warning in result.warnings)
    _assert_png_relationship(output)


def test_single_run_leading_and_trailing_spaces_are_preserved_once(tmp_path):
    document = Document()
    paragraph = document.add_paragraph()
    italic = paragraph.add_run("  note  ")
    italic.italic = True

    output, _ = _process_with_result(
        document, MockTranslationProvider(), tmp_path
    )
    body = output.paragraphs[0]

    assert body.runs[0].italic
    assert body.runs[0].text == "  [es] note  "


def test_table_cell_marker_mapping_preserves_formatting(tmp_path):
    """Formatting and association inside a table cell use the same path."""
    document = Document()
    table = document.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    paragraph = cell.paragraphs[0]
    bold = paragraph.add_run("Bold cell")
    bold.bold = True
    paragraph.add_run(" and ")
    italic = paragraph.add_run("italic cell")
    italic.italic = True

    result = _process(document, MockTranslationProvider(), tmp_path)
    cell_paragraph = result.tables[0].cell(0, 0).paragraphs[0]

    assert cell_paragraph.runs[0].bold
    assert cell_paragraph.runs[0].text == "[es] Bold cell"
    assert cell_paragraph.runs[2].italic
    assert cell_paragraph.runs[2].text == "italic cell"


def test_header_footer_marker_mapping_preserves_formatting(tmp_path):
    """Headers and footers use the same marker mapping path."""
    document = Document()

    header = document.sections[0].header.paragraphs[0]
    header_bold = header.add_run("Header ")
    header_bold.bold = True
    header_italic = header.add_run("note")
    header_italic.italic = True

    footer = document.sections[0].footer.paragraphs[0]
    footer_italic = footer.add_run("footer note")
    footer_italic.italic = True

    result = _process(document, MockTranslationProvider(), tmp_path)

    header_paragraph = result.sections[0].header.paragraphs[0]
    assert header_paragraph.runs[0].bold
    assert header_paragraph.runs[0].text == "[es] Header "
    assert header_paragraph.runs[1].italic
    assert header_paragraph.runs[1].text == "note"

    footer_paragraph = result.sections[0].footer.paragraphs[0]
    assert footer_paragraph.runs[0].italic
    assert footer_paragraph.runs[0].text == "[es] footer note"


def test_typed_page_break_in_run_is_preserved_with_warning(tmp_path):
    """A run carrying a typed page break keeps the break and records a shift."""
    document = Document()
    paragraph = document.add_paragraph()
    run = paragraph.add_run("Before")
    run.bold = True
    break_element = OxmlElement("w:br")
    break_element.set(qn("w:type"), "page")
    run._r.append(break_element)
    run.add_text(" after")

    output, result = _process_with_result(
        document, MockTranslationProvider(), tmp_path
    )
    body = output.paragraphs[0]

    assert body.runs[0].bold
    breaks = body.runs[0]._r.findall(qn("w:br"))
    assert any(
        element.get(qn("w:type")) == "page" for element in breaks
    )
    assert any("non-text content" in warning for warning in result.warnings)


def test_parse_marked_translation_accepts_well_formed_markers():
    result = _parse_marked_translation('[[[R0]]]Hello[[[/R0]]] [[[R1]]]world[[[/R1]]]', 2)
    assert result == ['Hello', 'world']


def test_parse_marked_translation_rejects_wrong_count():
    assert _parse_marked_translation('[[[R0]]]Hello[[[/R0]]]', 2) is None


def test_parse_marked_translation_rejects_reordered_markers():
    assert _parse_marked_translation('[[[R1]]]Hello[[[/R1]]]', 1) is None


def test_parse_marked_translation_rejects_empty_piece():
    assert _parse_marked_translation('[[[R0]]]   [[[R0]]]', 1) is None


def test_parse_marked_translation_rejects_trailing_text():
    assert _parse_marked_translation('[[[R0]]]Hello[[[/R0]]] trailing', 1) is None
