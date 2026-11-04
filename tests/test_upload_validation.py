import io
import zipfile
from uuid import uuid4

from app.models import Job, JobStatus, utcnow
from app.services.documents.validation import (
    MAX_DOCX_COMPRESSION_RATIO,
    MAX_DOCX_ENTRIES,
    MAX_DOCX_ENTRY_UNCOMPRESSED_BYTES,
    MAX_DOCX_UNCOMPRESSED_BYTES,
    sanitize_filename,
)
from tests.helpers import (
    make_blank_pdf_bytes,
    make_docx_bytes,
    make_pdf_bytes,
    upload,
)


def _make_zip(entries: list[tuple[str, bytes]], *, compress: bool = True) -> bytes:
    buffer = io.BytesIO()
    mode = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(buffer, "w", mode) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


def _docx_shell(entries: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    base = [("[Content_Types].xml", b"<Types/>"), ("word/document.xml", b"<doc/>")]
    return base + entries


def test_docx_zip_too_many_entries_is_rejected(client):
    entries = [(f"word/extra{i}.xml", b"x") for i in range(MAX_DOCX_ENTRIES + 5)]
    data = _make_zip(_docx_shell(entries))
    response = upload(client, data, filename="bomb.docx")
    assert response.status_code == 400
    assert "too many parts" in response.text.lower()


def test_docx_zip_oversized_entry_is_rejected(client):
    big = b"x" * (MAX_DOCX_ENTRY_UNCOMPRESSED_BYTES + 1024)
    data = _make_zip(_docx_shell([("word/big.bin", big)]))
    response = upload(client, data, filename="big.docx")
    assert response.status_code == 400
    assert "oversized part" in response.text.lower()


def test_docx_zip_excessive_total_uncompressed_is_rejected(client):
    # Several entries each under the per-entry cap but whose combined
    # uncompressed size exceeds the total cap. Data is moderately compressible
    # so the compression-ratio check does not fire first.
    pattern = (b"abcdefghij" * 10)  # 100 bytes
    chunk = pattern * (20 * 1024 * 1024 // len(pattern))
    entries = [("word/c0.bin", chunk), ("word/c1.bin", chunk), ("word/c2.bin", chunk)]
    data = _make_zip(_docx_shell(entries))
    response = upload(client, data, filename="total.docx")
    assert response.status_code == 400
    assert "too large when decompressed" in response.text.lower()


def test_docx_zip_suspicious_compression_ratio_is_rejected(client):
    # Highly compressible data in one entry creates an extreme ratio.
    big = b"\x00" * (2 * 1024 * 1024)
    data = _make_zip(_docx_shell([("word/huge.bin", big)]))
    response = upload(client, data, filename="ratio.docx")
    assert response.status_code == 400
    assert "suspicious compression ratio" in response.text.lower()


def _make_encrypted_like_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("word/document.xml", b"<doc/>")
    data = bytearray(buffer.getvalue())
    i = 0
    while True:
        idx = data.find(b"PK\x03\x04", i)
        if idx < 0:
            break
        data[idx + 6] |= 0x01
        i = idx + 4
    i = 0
    while True:
        idx = data.find(b"PK\x01\x02", i)
        if idx < 0:
            break
        data[idx + 8] |= 0x01
        i = idx + 4
    return bytes(data)


def test_encrypted_docx_is_rejected(client):
    data = _make_encrypted_like_zip()
    response = upload(client, data, filename="enc.docx")
    assert response.status_code == 400
    assert "encrypted" in response.text.lower()


def test_corrupt_docx_zip_is_rejected(client):
    data = bytearray(make_docx_bytes())
    # Flip a byte in the middle to corrupt compressed data.
    data[len(data) // 2] ^= 0xFF
    response = upload(client, bytes(data), filename="corrupt.docx")
    assert response.status_code == 400


def test_truncated_docx_zip_is_rejected(client):
    data = make_docx_bytes()[:50]
    response = upload(client, data, filename="trunc.docx")
    assert response.status_code == 400


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
