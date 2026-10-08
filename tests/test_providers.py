import os
import subprocess
import sys
from pathlib import Path

import pytest

import backend.providers as providers
from backend.records.local import SQLiteRecordStore
from backend.storage.local import LocalFileStorage

GETTERS = [providers.get_file_storage, providers.get_record_store, providers.get_vision_extractor]
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def local_provider(monkeypatch, tmp_path):
    """Use the local provider with temporary paths, and forget objects built by other tests."""
    monkeypatch.setattr(providers, "CLOUD_PROVIDER", "local")
    monkeypatch.setattr(providers, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(providers, "SQLITE_PATH", tmp_path / "receipts.db")
    for getter in GETTERS:
        getter.cache_clear()
    yield
    for getter in GETTERS:
        getter.cache_clear()


class FakeGeminiExtractor:
    """Stands in for GeminiVisionExtractor, which would need an API key and network calls."""


def test_local_provider_returns_the_local_implementations(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.extraction.direct_api.GeminiVisionExtractor", FakeGeminiExtractor)

    storage, store, extractor = (getter() for getter in GETTERS)

    assert isinstance(storage, LocalFileStorage) and storage.root == tmp_path / "uploads"
    assert isinstance(store, SQLiteRecordStore) and store.path == tmp_path / "receipts.db"
    assert isinstance(extractor, FakeGeminiExtractor)


def test_each_getter_builds_its_object_once():
    assert providers.get_file_storage() is providers.get_file_storage()
    assert providers.get_record_store() is providers.get_record_store()


@pytest.mark.parametrize("provider, phase", [("aws", "Phase 6"), ("azure", "Phase 7")])
@pytest.mark.parametrize("getter", GETTERS, ids=lambda getter: getter.__name__)
def test_cloud_providers_say_when_they_arrive(monkeypatch, getter, provider, phase):
    monkeypatch.setattr(providers, "CLOUD_PROVIDER", provider)

    with pytest.raises(NotImplementedError, match=phase):
        getter()


def test_local_provider_loads_no_cloud_sdk(tmp_path):
    # Run in a fresh interpreter: other tests may import cloud SDKs once Phases 6-7 add them
    code = (
        "import sys, backend.providers as p, backend.extraction.direct_api\n"
        "p.get_file_storage(); p.get_record_store()\n"
        "print(sorted({name.split('.')[0] for name in sys.modules} & {'boto3', 'botocore', 'azure'}))"
    )
    env = {**os.environ, "CLOUD_PROVIDER": "local", "SQLITE_PATH": str(tmp_path / "receipts.db"), "LOG_TO_FILE": "false"}

    result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "[]"
