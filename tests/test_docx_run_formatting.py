"""Focused regression tests for DOCX run-level formatting redistribution.

These tests deliberately separate two different claims:

* *property preservation* -- does the ``<w:i/>`` / ``<w:b/>`` element survive on
  its run after ``_rewrite_paragraph`` rewrites the run text?
* *text-to-formatting association* -- does the translated text that replaced the
  words that were originally inside a formatted run still live inside that same
  formatted run?

The provider contract returns flat translated strings with no word-level
alignment, so the second claim cannot be guaranteed by any redistribution
heuristic. Tests here assert the current, documented behaviour.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document

from app.services.documents.docx_processor import DocxProcessor
from app.services.translation.base import TranslationProvider, TranslationService


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


def _process(document: Document, provider: TranslationProvider, tmp_path: Path) -> Document:
    src = tmp_path / "in.docx"
    out = tmp_path / "out.docx"
    document.save(str(src))
    DocxProcessor(
        TranslationService(provider, max_retries=0, retry_backoff=0)
    ).process(src, out, "auto", "es")
    return Document(str(out))


def _mixed_paragraph(document: Document) -> None:
    """Plain "The " + italic "word" + plain " is here" (16 source chars)."""
    paragraph = document.add_paragraph()
    paragraph.add_run("The ")
    italic = paragraph.add_run("word")
    italic.italic = True
    paragraph.add_run(" is here")


def test_run_formatting_properties_survive_redistribution(tmp_path):
    """Bold and italic properties survive when the translation is longer."""
    document = Document()
    paragraph = document.add_paragraph()
    bold = paragraph.add_run("Bold product name")
    bold.bold = True
    paragraph.add_run(" and ")
    italic = paragraph.add_run("italic note")
    italic.italic = True

    result = _process(document, PrefixProvider(), tmp_path)
    body = result.paragraphs[0]

    assert any(run.bold for run in body.runs)
    assert any(run.italic for run in body.runs)
    # The mock-style prefix translation is long enough that the italic run
    # still receives text (this is the case the existing suite already covers).
    italic_runs = [run for run in body.runs if run.italic]
    assert italic_runs
    assert any(run.text for run in italic_runs)


def test_short_translation_can_empty_a_formatted_run(tmp_path):
    """A shorter translation can leave an originally non-empty formatted run empty.

    This documents the known limitation: the italic *property* survives on its
    run, but the translated text is no longer associated with that formatting.
    """
    document = Document()
    _mixed_paragraph(document)

    result = _process(document, ShortProvider(), tmp_path)
    body = result.paragraphs[0]

    # Property preservation still holds.
    assert any(run.italic for run in body.runs)

    # Text-to-formatting association does NOT hold: the italic run is empty.
    italic_runs = [run for run in body.runs if run.italic]
    assert italic_runs
    assert all(run.text == "" for run in italic_runs), (
        "Expected the redistribution to leave the italic run empty; this "
        "assertion documents the known formatting limitation."
    )


def test_mixed_bold_and_italic_runs_are_affected(tmp_path):
    """Both bold and italic runs can be emptied by a short translation.

    Paragraph layout mirrors the deterministic example: bold "The " (4),
    italic "word" (4), plain " is here" (8). A one-character translation
    distributes as ["", "", "X"], leaving both formatted runs empty.
    """
    document = Document()
    paragraph = document.add_paragraph()
    bold_a = paragraph.add_run("The ")
    bold_a.bold = True
    italic_b = paragraph.add_run("word")
    italic_b.italic = True
    paragraph.add_run(" is here")

    result = _process(document, ShortProvider(), tmp_path)
    body = result.paragraphs[0]

    bold_runs = [run for run in body.runs if run.bold]
    italic_runs = [run for run in body.runs if run.italic]
    assert bold_runs
    assert italic_runs
    assert all(run.text == "" for run in bold_runs)
    assert all(run.text == "" for run in italic_runs)
    # The plain remainder run holds the single translated character.
    plain_runs = [run for run in body.runs if not run.bold and not run.italic]
    assert any(run.text for run in plain_runs)


def test_table_cell_formatting_is_preserved(tmp_path):
    """Formatting inside a table cell is handled by the same code path."""
    document = Document()
    table = document.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    paragraph = cell.paragraphs[0]
    bold = paragraph.add_run("Bold cell")
    bold.bold = True
    paragraph.add_run(" and ")
    italic = paragraph.add_run("italic cell")
    italic.italic = True

    result = _process(document, PrefixProvider(), tmp_path)
    cell_paragraph = result.tables[0].cell(0, 0).paragraphs[0]

    assert any(run.bold for run in cell_paragraph.runs)
    assert any(run.italic for run in cell_paragraph.runs)


def test_header_footer_formatting_is_preserved(tmp_path):
    """Formatting inside headers and footers is handled by the same code path."""
    document = Document()

    header = document.sections[0].header.paragraphs[0]
    header_bold = header.add_run("Header ")
    header_bold.bold = True
    header_italic = header.add_run("note")
    header_italic.italic = True

    footer = document.sections[0].footer.paragraphs[0]
    footer_italic = footer.add_run("footer note")
    footer_italic.italic = True

    result = _process(document, PrefixProvider(), tmp_path)

    header_paragraph = result.sections[0].header.paragraphs[0]
    assert any(run.bold for run in header_paragraph.runs)
    assert any(run.italic for run in header_paragraph.runs)

    footer_paragraph = result.sections[0].footer.paragraphs[0]
    assert any(run.italic for run in footer_paragraph.runs)