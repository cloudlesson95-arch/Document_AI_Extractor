from functools import cache

from .config import (
    AZURE_BLOB_CONTAINER, AZURE_QUOTA_TABLE, AZURE_RECORDS_TABLE, AZURE_STORAGE_ACCOUNT, AZURE_STORAGE_CONNECTION_STRING,
    CLOUD_PROVIDER, DYNAMODB_QUOTA_TABLE, DYNAMODB_RECORDS_TABLE, S3_BUCKET, SQLITE_PATH, UPLOAD_DAILY_LIMIT, UPLOAD_DIR,
)
from .extraction.base import VisionExtractor
from .quota.base import UploadQuota
from .records.base import RecordStore
from .storage.base import FileStorage

# The only module that names concrete implementations: everything else asks for an interface here,
# so switching clouds is one CLOUD_PROVIDER change. Imports sit inside the branches, so each provider
# loads only its own cloud SDK, and `local` none. Each getter builds its object once, on first use.


def _unknown_provider() -> ValueError:
    # config.py accepts only local, aws and azure, so this means a getter is missing a branch
    return ValueError(f"No implementation for CLOUD_PROVIDER={CLOUD_PROVIDER!r}")


def _required(name: str, value: str) -> str:
    """Return a setting the chosen provider needs, or raise naming it, so a missing one isn't a cryptic SDK error."""
    if not value:
        raise RuntimeError(f"CLOUD_PROVIDER={CLOUD_PROVIDER!r} needs the {name} setting")
    return value


def _azure_storage_account() -> dict:
    """Where the `azure` provider's files, records and counts live: Azurite when its connection string is set,
    otherwise the account named by AZURE_STORAGE_ACCOUNT, signed in with the app's managed identity."""
    if AZURE_STORAGE_CONNECTION_STRING:
        return {"connection_string": AZURE_STORAGE_CONNECTION_STRING}
    return {"account": _required("AZURE_STORAGE_ACCOUNT", AZURE_STORAGE_ACCOUNT)}


@cache
def get_file_storage() -> FileStorage:
    if CLOUD_PROVIDER == "local":
        from .storage.local import LocalFileStorage
        return LocalFileStorage(UPLOAD_DIR)
    if CLOUD_PROVIDER == "aws":
        from .storage.s3 import S3FileStorage
        return S3FileStorage(_required("S3_BUCKET", S3_BUCKET))
    if CLOUD_PROVIDER == "azure":
        from .storage.blob import BlobFileStorage
        return BlobFileStorage(_required("AZURE_BLOB_CONTAINER", AZURE_BLOB_CONTAINER), **_azure_storage_account())
    raise _unknown_provider()


@cache
def get_record_store() -> RecordStore:
    if CLOUD_PROVIDER == "local":
        from .records.local import SQLiteRecordStore
        return SQLiteRecordStore(SQLITE_PATH)
    if CLOUD_PROVIDER == "aws":
        from .records.dynamo import DynamoDBRecordStore
        return DynamoDBRecordStore(_required("DYNAMODB_RECORDS_TABLE", DYNAMODB_RECORDS_TABLE))
    if CLOUD_PROVIDER == "azure":
        from .records.table import TableRecordStore
        return TableRecordStore(_required("AZURE_RECORDS_TABLE", AZURE_RECORDS_TABLE), **_azure_storage_account())
    raise _unknown_provider()


@cache
def get_vision_extractor() -> VisionExtractor:
    # Every provider calls the Gemini API; its key comes from the secret backend (Secrets Manager on AWS, Key Vault on Azure)
    from .extraction.direct_api import GeminiVisionExtractor
    return GeminiVisionExtractor()


@cache
def get_upload_quota() -> UploadQuota:
    if CLOUD_PROVIDER == "local":
        from .quota.local import SQLiteUploadQuota
        return SQLiteUploadQuota(SQLITE_PATH, UPLOAD_DAILY_LIMIT)
    if CLOUD_PROVIDER == "aws":
        from .quota.dynamo import DynamoDBUploadQuota
        return DynamoDBUploadQuota(_required("DYNAMODB_QUOTA_TABLE", DYNAMODB_QUOTA_TABLE), UPLOAD_DAILY_LIMIT)
    if CLOUD_PROVIDER == "azure":
        from .quota.table import TableUploadQuota
        return TableUploadQuota(_required("AZURE_QUOTA_TABLE", AZURE_QUOTA_TABLE), UPLOAD_DAILY_LIMIT,
                                **_azure_storage_account())
    raise _unknown_provider()
