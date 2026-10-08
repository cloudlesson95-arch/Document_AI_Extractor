import pytest

from backend.storage.base import FileStorage
from backend.storage.local import LocalFileStorage


@pytest.fixture(params=["local"])
def storage(request, tmp_path) -> FileStorage:
    # Every FileStorage must pass the tests that use this fixture; Phases 6-7 add S3 and Blob here
    if request.param == "local":
        return LocalFileStorage(tmp_path / "uploads")


def test_upload_then_download_returns_the_same_bytes(storage):
    key = storage.upload("receipts/abc.pdf", b"%PDF-1.4 content")

    assert key == "receipts/abc.pdf"
    assert storage.download(key) == b"%PDF-1.4 content"


def test_upload_replaces_an_existing_file(storage):
    storage.upload("receipts/abc.pdf", b"old")
    storage.upload("receipts/abc.pdf", b"new")

    assert storage.download("receipts/abc.pdf") == b"new"


@pytest.mark.parametrize("key", ["receipts/missing.pdf", "receipts"])  # "receipts" exists only as a folder
def test_download_of_a_missing_file_raises_file_not_found(storage, key):
    storage.upload("receipts/abc.pdf", b"x")

    with pytest.raises(FileNotFoundError):
        storage.download(key)


@pytest.mark.parametrize("key", [
    "", "/abs.pdf", "../escape.pdf", "receipts/../../escape.pdf", "receipts\\abc.pdf",
    "C:/abc.pdf", ".hidden", "receipts//abc.pdf", "receipts/",
])
def test_unsafe_keys_are_rejected(storage, key):
    with pytest.raises(ValueError):
        storage.upload(key, b"x")
    with pytest.raises(ValueError):
        storage.download(key)


def test_local_storage_writes_under_its_root_only_when_used(tmp_path):
    storage = LocalFileStorage(tmp_path / "uploads")
    assert not (tmp_path / "uploads").exists()  # nothing is created until the first upload

    storage.upload("receipts/abc.pdf", b"x")

    assert (tmp_path / "uploads" / "receipts" / "abc.pdf").read_bytes() == b"x"
