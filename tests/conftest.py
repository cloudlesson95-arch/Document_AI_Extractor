import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import backend.providers as providers
from backend import api
from backend.extraction.base import VisionExtractor
from backend.extraction.schema import ExtractedReceipt
from backend.utils.rate_limit import RateLimiter

GETTERS = [providers.get_file_storage, providers.get_record_store, providers.get_vision_extractor]


@pytest.fixture
def local_providers(monkeypatch, tmp_path):
    """Use the local provider with temporary paths, and forget objects built by other tests."""
    monkeypatch.setattr(providers, "CLOUD_PROVIDER", "local")
    monkeypatch.setattr(providers, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(providers, "SQLITE_PATH", tmp_path / "receipts.db")
    for getter in GETTERS:
        getter.cache_clear()
    yield
    for getter in GETTERS:
        getter.cache_clear()


class FakeExtractor(VisionExtractor):
    """Returns `receipt`, or raises `error` if set, instead of calling a model; records every call."""

    def __init__(self):
        self.receipt = ExtractedReceipt(
            vendor="Cafe Uno",
            date=datetime.date(2026, 9, 14),
            total_amount=Decimal("9.20"),
            currency="EUR",
            line_items=[{"description": "Latte", "quantity": 2, "unit_price": Decimal("3.75")}],
        )
        self.error: Exception | None = None
        self.calls: list[tuple[bytes, str]] = []

    def extract(self, content: bytes, mime_type: str) -> ExtractedReceipt:
        self.calls.append((content, mime_type))
        if self.error:
            raise self.error
        return self.receipt


@pytest.fixture
def fake_extractor(monkeypatch, local_providers) -> FakeExtractor:
    """The extractor get_vision_extractor() returns, in place of the Gemini one."""
    extractor = FakeExtractor()
    monkeypatch.setattr("backend.extraction.direct_api.GeminiVisionExtractor", lambda: extractor)
    return extractor


@pytest.fixture
def client(monkeypatch, local_providers, fake_extractor) -> TestClient:
    """The API on temporary local storage, with the fake extractor and a fresh upload rate limit."""
    monkeypatch.setattr(api, "upload_limiter", RateLimiter(max_calls=100))
    return TestClient(api.app)
