from __future__ import annotations

from contextlib import contextmanager

from app.models import Job, JobStatus, utcnow
from app.schemas import JobStatusResponse
from tests.helpers import make_docx_bytes, upload


def test_upload_cleans_up_file_on_database_failure(client, app, monkeypatch):
    @contextmanager
    def failing_session():
        raise RuntimeError("db failure")
        yield

    monkeypatch.setattr(app.state.database, "session", failing_session)

    uploads_before = list((app.state.settings.storage_path / "uploads").glob("*"))
    response = upload(client, make_docx_bytes(), filename="cleanup.docx")
    uploads_after = list((app.state.settings.storage_path / "uploads").glob("*"))

    assert response.status_code == 500
    assert len(uploads_after) == len(uploads_before)


def test_upload_preserves_original_error_when_cleanup_fails(client, app, monkeypatch):
    @contextmanager
    def failing_session():
        raise RuntimeError("db failure")
        yield

    def failing_delete(name):
        raise OSError("disk error")

    monkeypatch.setattr(app.state.database, "session", failing_session)
    monkeypatch.setattr(app.state.storage, "delete_upload", failing_delete)

    response = upload(client, make_docx_bytes(), filename="cleanup.docx")
    assert response.status_code == 500
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["provider"] == "mock"


def test_index_page_renders_form(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Translate export documents" in response.text
    assert 'name="target_language"' in response.text
    assert "Development mode" in response.text


def test_unknown_job_returns_404(client):
    assert client.get("/jobs/does-not-exist").status_code == 404
    assert client.get("/api/jobs/does-not-exist").status_code == 404
    assert client.get("/jobs/does-not-exist/download").status_code == 404


def test_completed_job_status_exposes_output_filename():
    now = utcnow()
    job = Job(
        id="test-job",
        original_filename="sample.docx",
        file_type="docx",
        source_language="auto",
        target_language="es",
        provider="mock",
        status=JobStatus.COMPLETED,
        output_path="generated.docx",
        output_filename="sample-es.docx",
        characters_translated=0,
        segments_translated=0,
        created_at=now,
        updated_at=now,
        completed_at=now,
    )

    response = JobStatusResponse.from_job(job)

    assert response.output_filename == "sample-es.docx"
