"""Focused tests for PDF font resolution and validation.

These tests exercise ``resolve_pdf_font`` directly with synthetic ``Settings``
instances so that missing fonts, invalid configured paths and Unicode coverage
gaps are covered without any live provider call.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import Field

from app.config import Settings
from app.errors import DocumentProcessingError
from app.services.documents.fonts import resolve_pdf_font


def _settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        database_url="sqlite:///:memory:",
        storage_root=Path("instance"),
        ai_provider="mock",
    )
    base.update(overrides)
    return Settings(**base)


def test_ascii_text_returns_none_when_no_font_available(tmp_path, monkeypatch):
    """Pure ASCII text needs no embedded font."""
    settings = _settings(pdf_font_path="")
    monkeypatch.setattr(
        "app.services.documents.fonts._FONT_CANDIDATES", []
    )
    assert resolve_pdf_font(settings, "Hello export invoice") is None


def test_missing_configured_font_path_is_skipped(tmp_path, monkeypatch):
    """A configured path that does not exist is skipped, not fatal."""
    missing = tmp_path / "does-not-exist.ttf"
    settings = _settings(pdf_font_path=str(missing))
    monkeypatch.setattr(
        "app.services.documents.fonts._FONT_CANDIDATES", []
    )
    assert resolve_pdf_font(settings, "plain ascii text") is None


def test_invalid_configured_font_path_with_non_ascii_raises(monkeypatch, tmp_path):
    """A configured path that exists but cannot load as a font fails loudly
    when non-ASCII text needs a font."""
    bad = tmp_path / "not-a-font.ttf"
    bad.write_bytes(b"not a real font file")
    settings = _settings(pdf_font_path=str(bad))
    monkeypatch.setattr(
        "app.services.documents.fonts._FONT_CANDIDATES", []
    )
    with pytest.raises(DocumentProcessingError) as exc_info:
        resolve_pdf_font(settings, "café")
    assert "PDF_FONT_PATH" in exc_info.value.user_message


def test_invalid_configured_font_path_with_ascii_is_safe(monkeypatch, tmp_path):
    """An unloadable configured font is harmless for pure ASCII text."""
    bad = tmp_path / "not-a-font.ttf"
    bad.write_bytes(b"not a real font file")
    settings = _settings(pdf_font_path=str(bad))
    monkeypatch.setattr(
        "app.services.documents.fonts._FONT_CANDIDATES", []
    )
    assert resolve_pdf_font(settings, "plain ascii text") is None


def test_non_ascii_without_font_raises(monkeypatch):
    """Non-ASCII text with no usable font raises a clear error."""
    settings = _settings(pdf_font_path="")
    monkeypatch.setattr(
        "app.services.documents.fonts._FONT_CANDIDATES", []
    )
    with pytest.raises(DocumentProcessingError) as exc_info:
        resolve_pdf_font(settings, "café résumé")
    assert "no available font" in exc_info.value.user_message.lower()


def test_configured_font_with_full_coverage_is_preferred(monkeypatch, tmp_path):
    """A configured font that covers the required glyphs wins."""
    real = Path(r"C:\Windows\Fonts\arialuni.ttf")
    if not real.is_file():
        pytest.skip("Windows Arial Unicode font not available on this machine")
    settings = _settings(pdf_font_path=str(real))
    result = resolve_pdf_font(settings, "café")
    assert result == str(real)


def test_relative_pdf_font_path_is_resolved_against_project_root(monkeypatch, tmp_path):
    """A relative PDF_FONT_PATH resolves against the project root, not cwd."""
    real = Path(r"C:\Windows\Fonts\arialuni.ttf")
    if not real.is_file():
        pytest.skip("Windows Arial Unicode font not available on this machine")
    import app.services.documents.fonts as fonts_module

    target = tmp_path / "relative-font.ttf"
    target.write_bytes(real.read_bytes())
    monkeypatch.setattr(fonts_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path.parent)  # run from a different working directory
    settings = _settings(pdf_font_path="relative-font.ttf")
    result = resolve_pdf_font(settings, "café")
    assert result == str(target.resolve())
