import os
import subprocess
import sys
from pathlib import Path

import pytest

import backend.providers as providers
from backend.quota.dynamo import DynamoDBUploadQuota
from backend.quota.local import SQLiteUploadQuota
from backend.records.dynamo import DynamoDBRecordStore
from backend.records.local import SQLiteRecordStore
from backend.storage.local import LocalFileStorage
from backend.storage.s3 import S3FileStorage

GETTERS = [providers.get_file_storage, providers.get_record_store, providers.get_vision_extractor,
           providers.get_upload_quota]
REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.usefixtures("local_providers")  # from conftest.py


class FakeGeminiExtractor:
    """Stands in for GeminiVisionExtractor, which would need an API key and network calls."""


def test_local_provider_returns_the_local_implementations(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.extraction.direct_api.GeminiVisionExtractor", FakeGeminiExtractor)
    monkeypatch.setattr(providers, "UPLOAD_DAILY_LIMIT", 7)

    storage, store, extractor, quota = (getter() for getter in GETTERS)

    assert isinstance(storage, LocalFileStorage) and storage.root == tmp_path / "uploads"
    assert isinstance(store, SQLiteRecordStore) and store.path == tmp_path / "receipts.db"
    assert isinstance(extractor, FakeGeminiExtractor)
    assert isinstance(quota, SQLiteUploadQuota) and (quota.path, quota.limit) == (tmp_path / "receipts.db", 7)


@pytest.fixture
def aws_provider(monkeypatch, local_providers, aws):
    """CLOUD_PROVIDER=aws with every setting it needs, inside moto (aws, from conftest.py)."""
    monkeypatch.setattr(providers, "CLOUD_PROVIDER", "aws")
    monkeypatch.setattr(providers, "S3_BUCKET", "uploads-bucket")
    monkeypatch.setattr(providers, "DYNAMODB_RECORDS_TABLE", "receipts-table")
    monkeypatch.setattr(providers, "DYNAMODB_QUOTA_TABLE", "quota-table")
    monkeypatch.setattr(providers, "UPLOAD_DAILY_LIMIT", 7)


def test_aws_provider_returns_s3_dynamodb_and_the_gemini_extractor(monkeypatch, aws_provider):
    monkeypatch.setattr("backend.extraction.direct_api.GeminiVisionExtractor", FakeGeminiExtractor)

    storage, store, extractor, quota = (getter() for getter in GETTERS)

    assert isinstance(storage, S3FileStorage) and storage.bucket == "uploads-bucket"
    assert isinstance(store, DynamoDBRecordStore) and store.table == "receipts-table"
    assert isinstance(extractor, FakeGeminiExtractor)  # the Gemini API, as locally
    assert isinstance(quota, DynamoDBUploadQuota) and (quota.table, quota.limit) == ("quota-table", 7)


@pytest.mark.parametrize("setting, getter", [
    ("S3_BUCKET", providers.get_file_storage),
    ("DYNAMODB_RECORDS_TABLE", providers.get_record_store),
    ("DYNAMODB_QUOTA_TABLE", providers.get_upload_quota),
], ids=["S3_BUCKET", "DYNAMODB_RECORDS_TABLE", "DYNAMODB_QUOTA_TABLE"])
def test_aws_provider_names_a_missing_setting(monkeypatch, aws_provider, setting, getter):
    monkeypatch.setattr(providers, setting, "")

    with pytest.raises(RuntimeError, match=setting):
        getter()


def test_each_getter_builds_its_object_once():
    assert providers.get_file_storage() is providers.get_file_storage()
    assert providers.get_record_store() is providers.get_record_store()
    assert providers.get_upload_quota() is providers.get_upload_quota()


@pytest.mark.parametrize("provider, phase", [("azure", "Phase 7")])
@pytest.mark.parametrize("getter", GETTERS, ids=lambda getter: getter.__name__)
def test_cloud_providers_say_when_they_arrive(monkeypatch, getter, provider, phase):
    monkeypatch.setattr(providers, "CLOUD_PROVIDER", provider)

    with pytest.raises(NotImplementedError, match=phase):
        getter()


def test_local_provider_loads_no_cloud_sdk(tmp_path):
    # Run in a fresh interpreter: other tests import boto3
    code = (
        "import sys, backend.providers as p, backend.extraction.direct_api\n"
        "p.get_file_storage(); p.get_record_store(); p.get_upload_quota()\n"
        "print(sorted({name.split('.')[0] for name in sys.modules} & {'boto3', 'botocore', 'azure'}))"
    )
    env = {**os.environ, "CLOUD_PROVIDER": "local", "SQLITE_PATH": str(tmp_path / "receipts.db"), "LOG_TO_FILE": "false"}

    result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "[]"
