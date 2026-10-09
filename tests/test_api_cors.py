import pytest
from fastapi.testclient import TestClient

import backend.providers as providers
from backend import api
from backend.records.local import SQLiteRecordStore

ALLOWED = "http://localhost:3000"  # the CORS_ALLOW_ORIGINS default; run the tests without that variable set
PREFLIGHT = {"Access-Control-Request-Method": "PATCH", "Access-Control-Request-Headers": "content-type"}

pytestmark = pytest.mark.usefixtures("local_providers")  # requests that reach a route use temporary storage


def test_preflight_from_the_frontend_origin_is_allowed():
    """Verify the browser's preflight for a JSON PATCH from the frontend's origin succeeds."""
    response = TestClient(api.app).options("/receipts/abc", headers={"Origin": ALLOWED, **PREFLIGHT})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert "PATCH" in response.headers["access-control-allow-methods"]


def test_preflight_from_another_origin_is_refused():
    """Verify an origin that isn't configured gets no CORS permission."""
    response = TestClient(api.app).options("/receipts/abc", headers={"Origin": "https://evil.example", **PREFLIGHT})

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_error_responses_carry_cors_headers_and_expose_retry_after():
    """Verify an error response still names the frontend's origin, so its JavaScript can read the status, detail and Retry-After."""
    response = TestClient(api.app).get("/receipts/does-not-exist", headers={"Origin": ALLOWED})

    assert response.status_code == 404
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert "retry-after" in response.headers["access-control-expose-headers"].lower()


def test_unexpected_errors_answer_500_with_cors_headers(monkeypatch):
    """Verify a crash still reaches the browser as a readable 500, not as a CORS error."""
    def broken_search(self, filters=None):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(SQLiteRecordStore, "search", broken_search)

    response = TestClient(api.app).get("/receipts", headers={"Origin": ALLOWED})

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}  # no internals
    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_a_cloud_provider_that_isnt_implemented_answers_503_with_cors_headers(monkeypatch):
    """Verify an aws or azure deployment before Phase 6 or 7 says why it can't serve receipts."""
    monkeypatch.setattr(providers, "CLOUD_PROVIDER", "aws")

    response = TestClient(api.app).get("/receipts", headers={"Origin": ALLOWED})

    assert response.status_code == 503
    assert "Phase 6" in response.json()["detail"]
    assert response.headers["access-control-allow-origin"] == ALLOWED
