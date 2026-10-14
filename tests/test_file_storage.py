import boto3
import pytest
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient

from backend.storage.base import FileStorage
from backend.storage.blob import BlobFileStorage
from backend.storage.local import LocalFileStorage
from backend.storage.s3 import S3FileStorage


@pytest.fixture(params=["local", "s3", "blob"])
def storage(request, tmp_path) -> FileStorage:
    # Every FileStorage must pass the tests that use this fixture
    if request.param == "local":
        return LocalFileStorage(tmp_path / "uploads")
    if request.param == "s3":
        return S3FileStorage(request.getfixturevalue("s3_bucket"))  # in moto's S3, from conftest.py
    if request.param == "blob":  # in Azurite, from conftest.py
        return BlobFileStorage(request.getfixturevalue("blob_container"), connection_string=request.getfixturevalue("azurite"))


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


def test_s3_storage_keeps_each_file_as_an_object_named_by_its_key(s3_bucket):
    S3FileStorage(s3_bucket).upload("receipts/abc.pdf", b"x")

    assert boto3.client("s3").get_object(Bucket=s3_bucket, Key="receipts/abc.pdf")["Body"].read() == b"x"


def test_blob_storage_keeps_each_file_as_a_blob_named_by_its_key(azurite, blob_container):
    BlobFileStorage(blob_container, connection_string=azurite).upload("receipts/abc.pdf", b"x")

    container = BlobServiceClient.from_connection_string(azurite).get_container_client(blob_container)
    assert container.download_blob("receipts/abc.pdf").readall() == b"x"


def test_blob_storage_without_its_container_raises_instead_of_reporting_a_missing_file(azurite):
    # A missing container is a misconfiguration: the API must answer 500, not 404 for every receipt's original
    storage = BlobFileStorage("no-such-container", connection_string=azurite)

    with pytest.raises(ResourceNotFoundError):
        storage.download("receipts/abc.pdf")
