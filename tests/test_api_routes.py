from fastapi.testclient import TestClient

from backend import api


def test_health_reports_the_provider_and_the_deployed_revision(monkeypatch):
    monkeypatch.setattr(api, "APP_REVISION", "abc1234")

    response = TestClient(api.app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "cloud_provider": api.CLOUD_PROVIDER, "revision": "abc1234"}


def test_health_reports_no_revision_when_none_is_deployed(monkeypatch):
    monkeypatch.setattr(api, "APP_REVISION", "")

    assert TestClient(api.app).get("/health").json()["revision"] is None
