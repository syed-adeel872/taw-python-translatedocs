from __future__ import annotations

from uuid import uuid4

from app.models import Job, JobStatus, utcnow
from app.services.documents.validation import sanitize_filename
from tests.helpers import (
    make_blank_pdf_bytes,
    make_docx_bytes,
    make_pdf_bytes,
    upload,
)


def test_unsupported_extension_is_rejected(client):
    response = upload(client, b"hello", filename="notes.txt")
    assert response.status_code == 400
    assert "Unsupported file type" in response.text


def test_empty_upload_is_rejected(client):
    response = upload(client, b"", filename="empty.pdf")
    assert response.status_code == 400
    assert "empty" in response.text.lower()


def test_spoofed_docx_extension_is_rejected(client):
    response = upload(client, b"this is not a zip file", filename="fake.docx")
    assert response.status_code == 400
    assert "corrupted" in response.text.lower()


def test_corrupted_pdf_is_rejected(client):
    response = upload(client, b"%PDF-1.7\nbroken", filename="broken.pdf")
    assert response.status_code == 400
    assert "corrupted" in response.text.lower()


def test_password_protected_pdf_is_rejected(client):
    response = upload(
        client,
        make_pdf_bytes(password="client-secret"),
        filename="protected.pdf",
    )
    assert response.status_code == 400
    assert "password" in response.text.lower()


def test_oversized_upload_is_rejected(client):
    response = upload(
        client, b"x" * (1024 * 1024 + 10), filename="huge.pdf"
    )
    assert response.status_code == 413
    assert "larger than" in response.text


def test_invalid_target_language_is_rejected(client):
    response = upload(client, make_docx_bytes(), target="xx")
    assert response.status_code == 400
    assert "supported target language" in response.text.lower()


def test_filename_path_traversal_is_neutralised(client, app):
    response = upload(client, make_docx_bytes(), filename="../../evil.docx")
    assert response.status_code == 303
    job_id = response.headers["location"].rsplit("/", 1)[-1]

    with app.state.database.session() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.original_filename == "evil.docx"


def test_sanitize_filename_removes_paths_and_control_characters():
    assert sanitize_filename(r"..\..\secret.docx") == "secret.docx"
    assert sanitize_filename("/tmp/../invoice.pdf") == "invoice.pdf"
    assert sanitize_filename("bad\x00name\n.docx") == "badname.docx"
    assert sanitize_filename("") == "document"


def test_missing_output_file_returns_404(client, app):
    with app.state.database.session() as session:
        job = Job(
            id=uuid4().hex,
            original_filename="gone.docx",
            file_type="docx",
            source_language="auto",
            target_language="es",
            provider="mock",
            status=JobStatus.COMPLETED,
            output_path="missing-output.docx",
            output_filename="gone-es.docx",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(job)
        session.commit()
        job_id = job.id

    response = client.get(f"/jobs/{job_id}/download")
    assert response.status_code == 404
    assert "no longer available" in response.json()["detail"].lower()


def test_scanned_pdf_is_rejected_with_ocr_explanation(client):
    response = upload(client, make_blank_pdf_bytes(), filename="scan.pdf")
    assert response.status_code == 303
    job_id = response.headers["location"].rsplit("/", 1)[-1]

    payload = client.get(f"/api/jobs/{job_id}").json()
    assert payload["status"] == "failed"
    assert "ocr" in payload["error_message"].lower()
