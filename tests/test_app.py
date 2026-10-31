from __future__ import annotations


def test_health_reports_ok(client):
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
