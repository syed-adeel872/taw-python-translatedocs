from __future__ import annotations

from io import BytesIO
from uuid import uuid4

from docx import Document

from app.errors import ProviderConfigurationError, RateLimitError, TranslationError
from app.models import Job, JobStatus, utcnow
from app.services.translation.base import TranslationProvider, TranslationService
from tests.helpers import (
    make_docx_bytes,
    make_empty_docx_bytes,
    make_invalid_docx_zip,
    upload,
)


class AlwaysFailingProvider(TranslationProvider):
    name = "always-failing"

    def translate(self, texts, source_language, target_language):
        raise ProviderConfigurationError("The test provider is deliberately failing.")


class WrongLengthProvider(TranslationProvider):
    name = "wrong-length"

    def translate(self, texts, source_language, target_language):
        return ["only one result"]


def _job_id(response) -> str:
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    assert location.startswith("/jobs/")
    return location.rsplit("/", 1)[-1]


def _collect_docx_text(document: Document) -> str:
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    for section in document.sections:
        parts.extend(paragraph.text for paragraph in section.header.paragraphs)
        parts.extend(paragraph.text for paragraph in section.footer.paragraphs)
    return "\n".join(parts)


def test_valid_docx_upload_translates_and_downloads(client, app, settings):
    response = upload(client, make_docx_bytes())
    job_id = _job_id(response)

    page = client.get(f"/jobs/{job_id}")
    assert page.status_code == 200
    assert "sample.docx" in page.text

    status = client.get(f"/api/jobs/{job_id}")
    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] == "completed"
    assert payload["provider"] == "mock"
    assert payload["segments_translated"] == 5
    assert payload["download_url"] == f"/jobs/{job_id}/download"
    assert payload["warnings"]

    download = client.get(f"/jobs/{job_id}/download")
    assert download.status_code == 200
    assert "sample-es.docx" in download.headers["content-disposition"]
    assert (
        download.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    output = Document(BytesIO(download.content))
    text = _collect_docx_text(output)
    assert "[es] Export summary" in text
    assert "[es] Quantity 120 cartons" in text
    assert "[es] Trading company header" in text
    assert "[es] Bold product name and italic note" in text

    heading = output.paragraphs[0]
    assert heading.style.name == "Heading 1"
    assert heading.text == "[es] Export summary"

    body_runs = output.paragraphs[1].runs
    assert any(run.bold for run in body_runs)
    assert any(run.italic for run in body_runs)

    assert list((settings.storage_root / "uploads").iterdir()) == []

    with app.state.database.session() as session:
        persisted = session.get(Job, job_id)
        assert persisted is not None
        assert persisted.status == JobStatus.COMPLETED
        assert persisted.original_filename == "sample.docx"
        assert persisted.target_language == "es"
        assert persisted.output_filename == "sample-es.docx"
        assert persisted.characters_translated > 0
        assert persisted.output_path


def test_empty_docx_fails_with_clear_message(client):
    response = upload(client, make_empty_docx_bytes())
    job_id = _job_id(response)
    payload = client.get(f"/api/jobs/{job_id}").json()

    assert payload["status"] == "failed"
    assert "no translatable text" in payload["error_message"].lower()


def test_structurally_invalid_docx_fails_during_processing(client):
    response = upload(client, make_invalid_docx_zip())
    job_id = _job_id(response)
    payload = client.get(f"/api/jobs/{job_id}").json()

    assert payload["status"] == "failed"
    assert "could not be opened" in payload["error_message"].lower()


def test_translation_provider_failure_is_reported(client, app):
    app.state.runner.translator = TranslationService(
        AlwaysFailingProvider(), max_retries=0, retry_backoff=0
    )
    response = upload(client, make_docx_bytes())
    job_id = _job_id(response)
    payload = client.get(f"/api/jobs/{job_id}").json()

    assert payload["status"] == "failed"
    assert "deliberately failing" in payload["error_message"]

    download = client.get(f"/jobs/{job_id}/download")
    assert download.status_code == 409


def test_malformed_provider_response_fails_job(client, app):
    app.state.runner.translator = TranslationService(
        WrongLengthProvider(), max_retries=0, retry_backoff=0
    )
    response = upload(client, make_docx_bytes())
    job_id = _job_id(response)
    payload = client.get(f"/api/jobs/{job_id}").json()

    assert payload["status"] == "failed"
    assert "could not understand" in payload["error_message"].lower()


def test_download_in_progress_job_returns_409(client, app):
    with app.state.database.session() as session:
        job = Job(
            id=uuid4().hex,
            original_filename="pending.docx",
            file_type="docx",
            source_language="auto",
            target_language="es",
            provider="mock",
            status=JobStatus.PROCESSING,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(job)
        session.commit()
        job_id = job.id

    response = client.get(f"/jobs/{job_id}/download")
    assert response.status_code == 409
    assert "still in progress" in response.json()["detail"].lower()


def test_retry_on_rate_limit_then_success():
    calls = {"count": 0}

    class FlakyProvider(TranslationProvider):
        name = "flaky"

        def translate(self, texts, source_language, target_language):
            calls["count"] += 1
            if calls["count"] <= 2:
                raise RateLimitError()
            return [f"[{target_language}] {text}" for text in texts]

    service = TranslationService(
        FlakyProvider(), max_retries=2, retry_backoff=0, batch_size=10
    )
    result = service.translate_texts(["one", "two", "three"], "auto", "fr")

    assert calls["count"] == 3
    assert result == ["[fr] one", "[fr] two", "[fr] three"]


def test_retry_gives_up_after_max_attempts():
    class AlwaysRateLimited(TranslationProvider):
        name = "limited"

        def translate(self, texts, source_language, target_language):
            raise RateLimitError()

    service = TranslationService(
        AlwaysRateLimited(), max_retries=1, retry_backoff=0
    )
    try:
        service.translate_texts(["hello"], "auto", "es")
    except RateLimitError:
        pass
    else:
        raise AssertionError("RateLimitError was not raised")


def test_document_character_limit_is_enforced():
    service = TranslationService(
        AlwaysFailingProvider(), max_retries=0, max_document_chars=5
    )
    try:
        service.translate_texts(["this is too long"], "auto", "es")
    except TranslationError as exc:
        assert "too large" in exc.user_message.lower()
    else:
        raise AssertionError("TranslationError was not raised")
