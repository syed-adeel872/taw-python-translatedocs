from __future__ import annotations

import pymupdf as fitz

from app.services.translation.base import TranslationProvider, TranslationService
from tests.helpers import make_pdf_bytes, upload


class PdfFailingProvider(TranslationProvider):
    name = "pdf-failing"

    def translate(self, texts, source_language, target_language):
        raise RuntimeError("provider exploded")


def test_pdf_upload_preserves_page_sizes_and_downloads(client, settings):
    source = make_pdf_bytes()
    response = upload(client, source, filename="invoice.pdf", target="fr")
    assert response.status_code == 303
    job_id = response.headers["location"].rsplit("/", 1)[-1]

    payload = client.get(f"/api/jobs/{job_id}").json()
    assert payload["status"] == "completed", payload.get("error_message")
    assert payload["file_type"] == "pdf"
    assert payload["segments_translated"] == 2
    assert any("page" in warning.lower() for warning in payload["warnings"])

    download = client.get(f"/jobs/{job_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert "invoice-fr.pdf" in download.headers["content-disposition"]

    output = fitz.open(stream=download.content, filetype="pdf")
    try:
        assert output.page_count == 2
        first = output[0]
        second = output[1]
        assert round(first.rect.width, 1) == 400.0
        assert round(first.rect.height, 1) == 500.0
        assert round(second.rect.width, 1) == 300.0
        assert round(second.rect.height, 1) == 600.0

        first_text = first.get_text().replace("\xa0", " ")
        second_text = second.get_text().replace("\xa0", " ")
        assert "[fr]" in first_text
        assert "[fr]" in second_text
        assert "Hello export invoice" in first_text
        assert "Second page terms" in second_text
    finally:
        output.close()

    assert list((settings.storage_root / "uploads").iterdir()) == []


def test_pdf_failure_removes_partial_output(client, app, settings):
    app.state.runner.translator = TranslationService(
        PdfFailingProvider(), max_retries=0, retry_backoff=0
    )
    response = upload(client, make_pdf_bytes(), filename="broken-output.pdf")
    assert response.status_code == 303
    job_id = response.headers["location"].rsplit("/", 1)[-1]

    payload = client.get(f"/api/jobs/{job_id}").json()
    assert payload["status"] == "failed"
    assert "unexpected error" in payload["error_message"].lower()
    assert list((settings.storage_root / "outputs").iterdir()) == []
    assert list((settings.storage_root / "uploads").iterdir()) == []
