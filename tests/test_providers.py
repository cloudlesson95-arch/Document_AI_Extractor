import os
import subprocess
import sys
from pathlib import Path

import pytest

import backend.providers as providers
from backend.quota.dynamo import DynamoDBUploadQuota
from backend.quota.local import SQLiteUploadQuota
from backend.quota.table import TableUploadQuota
from backend.records.dynamo import DynamoDBRecordStore
from backend.records.local import SQLiteRecordStore
from backend.records.table import TableRecordStore
from backend.storage.blob import BlobFileStorage
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


@pytest.fixture
def azure_provider(monkeypatch, local_providers):
    """CLOUD_PROVIDER=azure with every setting it needs. Building the clients makes no network call."""
    monkeypatch.setattr(providers, "CLOUD_PROVIDER", "azure")
    monkeypatch.setattr(providers, "AZURE_STORAGE_ACCOUNT", "docaitest")
    monkeypatch.setattr(providers, "AZURE_STORAGE_CONNECTION_STRING", "")
    monkeypatch.setattr(providers, "AZURE_BLOB_CONTAINER", "uploads")
    monkeypatch.setattr(providers, "AZURE_RECORDS_TABLE", "receipts")
    monkeypatch.setattr(providers, "AZURE_QUOTA_TABLE", "uploadcounts")
    monkeypatch.setattr(providers, "UPLOAD_DAILY_LIMIT", 7)


def test_azure_provider_returns_blob_and_table_storage_and_the_gemini_extractor(monkeypatch, azure_provider):
    monkeypatch.setattr("backend.extraction.direct_api.GeminiVisionExtractor", FakeGeminiExtractor)

    storage, store, extractor, quota = (getter() for getter in GETTERS)

    assert isinstance(storage, BlobFileStorage) and storage.container == "uploads"
    assert storage._container.url == "https://docaitest.blob.core.windows.net/uploads"
    assert isinstance(store, TableRecordStore) and store.table == "receipts"
    assert store._table.url == "https://docaitest.table.core.windows.net"
    assert isinstance(extractor, FakeGeminiExtractor)  # the Gemini API, as on the other providers
    assert isinstance(quota, TableUploadQuota) and (quota.table, quota.limit) == ("uploadcounts", 7)


def test_azure_provider_uses_azurite_when_its_connection_string_is_set(monkeypatch, azure_provider):
    monkeypatch.setattr(providers, "AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    monkeypatch.setattr(providers, "AZURE_STORAGE_ACCOUNT", "")  # not needed then

    assert providers.get_file_storage()._container.url == "http://127.0.0.1:10000/devstoreaccount1/uploads"
    assert providers.get_record_store()._table.url == "http://127.0.0.1:10002/devstoreaccount1"


@pytest.mark.parametrize("setting, getter", [
    ("AZURE_STORAGE_ACCOUNT", providers.get_file_storage),
    ("AZURE_BLOB_CONTAINER", providers.get_file_storage),
    ("AZURE_RECORDS_TABLE", providers.get_record_store),
    ("AZURE_QUOTA_TABLE", providers.get_upload_quota),
], ids=["AZURE_STORAGE_ACCOUNT", "AZURE_BLOB_CONTAINER", "AZURE_RECORDS_TABLE", "AZURE_QUOTA_TABLE"])
def test_azure_provider_names_a_missing_setting(monkeypatch, azure_provider, setting, getter):
    monkeypatch.setattr(providers, setting, "")

    with pytest.raises(RuntimeError, match=setting):
        getter()


def test_each_getter_builds_its_object_once():
    assert providers.get_file_storage() is providers.get_file_storage()
    assert providers.get_record_store() is providers.get_record_store()
    assert providers.get_upload_quota() is providers.get_upload_quota()


@pytest.mark.parametrize("getter", [providers.get_file_storage, providers.get_record_store, providers.get_upload_quota],
                         ids=lambda getter: getter.__name__)
def test_a_provider_without_a_branch_is_refused(monkeypatch, getter):
    monkeypatch.setattr(providers, "CLOUD_PROVIDER", "gcp")

    with pytest.raises(ValueError, match="gcp"):
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


@pytest.mark.parametrize("provider, settings, sdks", [
    # boto3 takes the region from AWS_DEFAULT_REGION (Lambda sets it), not AWS_REGION
    ("aws", {"S3_BUCKET": "b", "DYNAMODB_RECORDS_TABLE": "r", "DYNAMODB_QUOTA_TABLE": "q", "AWS_DEFAULT_REGION": "us-east-1"},
     ["boto3", "botocore"]),
    ("azure", {"AZURE_STORAGE_ACCOUNT": "a", "AZURE_BLOB_CONTAINER": "c", "AZURE_RECORDS_TABLE": "r",
               "AZURE_QUOTA_TABLE": "q"}, ["azure"]),
])
def test_each_cloud_provider_loads_only_its_own_sdk(provider, settings, sdks):
    # Both SDKs are in one image; the providers must not load each other's. Building the clients makes no network call.
    code = (
        "import sys, backend.providers as p, backend.extraction.direct_api\n"
        "p.get_file_storage(); p.get_record_store(); p.get_upload_quota()\n"
        "print(sorted({name.split('.')[0] for name in sys.modules} & {'boto3', 'botocore', 'azure'}))"
    )
    env = {**os.environ, "CLOUD_PROVIDER": provider, "LOG_TO_FILE": "false", "AZURE_STORAGE_CONNECTION_STRING": "", **settings}

    result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)

    assert result.stdout.strip() == str(sdks)
