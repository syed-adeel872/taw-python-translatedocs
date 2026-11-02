from __future__ import annotations


def test_security_headers_are_set(client):
    response = client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_job_routes_are_not_cached(client):
    response = client.get("/jobs/does-not-exist")
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
