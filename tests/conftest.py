import datetime
import os
import socket
import uuid
from decimal import Decimal

import boto3
import pytest
from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobServiceClient
from fastapi.testclient import TestClient
from moto import mock_aws

import backend.providers as providers
from backend import api
from backend.extraction.base import VisionExtractor
from backend.extraction.schema import ExtractedReceipt
from backend.utils.rate_limit import RateLimiter

GETTERS = [providers.get_file_storage, providers.get_record_store, providers.get_vision_extractor,
           providers.get_upload_quota]


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


@pytest.fixture
def aws(monkeypatch):
    """moto's in-memory AWS, with fake credentials and region, so no test can reach a real account."""
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(name, "testing")
    for name in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        monkeypatch.setenv(name, "us-east-1")
    with mock_aws():
        yield


@pytest.fixture
def s3_bucket(aws) -> str:
    """An empty bucket in moto's S3."""
    boto3.client("s3").create_bucket(Bucket="test-uploads")
    return "test-uploads"


def create_dynamodb_table(name: str, key: str) -> str:
    """An on-demand table in moto's DynamoDB whose only key is the string attribute `key`, as deployed."""
    boto3.client("dynamodb").create_table(
        TableName=name,
        KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return name


@pytest.fixture
def records_table(aws) -> str:
    return create_dynamodb_table("test-receipts", "id")


@pytest.fixture
def quota_table(aws) -> str:
    return create_dynamodb_table("test-upload-counts", "day")


# Azurite, Azure's storage emulator, on its default ports; this connection string needs no account key
AZURITE = "UseDevelopmentStorage=true"
AZURITE_COMMAND = (
    "docker run -d --rm -p 127.0.0.1:10000:10000 -p 127.0.0.1:10002:10002 mcr.microsoft.com/azure-storage/azurite:3.37.0 "
    "azurite --blobHost 0.0.0.0 --tableHost 0.0.0.0 --inMemoryPersistence --skipApiVersionCheck"
)


@pytest.fixture(scope="session")
def azurite() -> str:
    """Azurite's connection string. Without Azurite, its tests are skipped, or fail where REQUIRE_AZURITE is set (CI)."""
    for port in (10000, 10002):  # Blob and Table Storage
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
        except OSError:
            message = f"Azurite isn't running on 127.0.0.1:{port}; start it with: {AZURITE_COMMAND}"
            if os.getenv("REQUIRE_AZURITE"):
                pytest.fail(message)
            pytest.skip(message)
    return AZURITE


@pytest.fixture
def blob_container(azurite) -> str:
    """An empty container in Azurite, deleted after the test."""
    service = BlobServiceClient.from_connection_string(azurite)
    name = f"test-{uuid.uuid4().hex}"
    service.create_container(name)
    yield name
    service.delete_container(name)


@pytest.fixture
def azure_table(azurite) -> str:
    """An empty table in Azurite, deleted after the test."""
    service = TableServiceClient.from_connection_string(azurite)
    name = f"test{uuid.uuid4().hex}"  # letters and digits only
    service.create_table(name)
    yield name
    service.delete_table(name)


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


class FakeCategorizer:
    """Returns `category`, or raises `error` if set, instead of running the classifier; records every call."""

    def __init__(self):
        self.category: str | None = "Meals"
        self.error: Exception | None = None
        self.calls: list[ExtractedReceipt] = []

    def predict(self, receipt: ExtractedReceipt) -> str | None:
        self.calls.append(receipt)
        if self.error:
            raise self.error
        return self.category


@pytest.fixture
def fake_categorizer(monkeypatch) -> FakeCategorizer:
    """The categorizer the API uses, in place of the trained one, so API tests don't depend on the training data."""
    categorizer = FakeCategorizer()
    monkeypatch.setattr(api, "get_categorizer", lambda: categorizer)
    return categorizer


@pytest.fixture
def client(monkeypatch, local_providers, fake_extractor, fake_categorizer) -> TestClient:
    """The API on temporary local storage, with the fake extractor and categorizer and fresh, high upload limits."""
    monkeypatch.setattr(api, "upload_limiter", RateLimiter(max_calls=100))
    monkeypatch.setattr(providers, "UPLOAD_DAILY_LIMIT", 100)  # the daily count starts at 0 in each test's database
    return TestClient(api.app)
