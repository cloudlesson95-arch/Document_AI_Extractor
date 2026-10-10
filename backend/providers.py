from functools import cache

from .config import (
    CLOUD_PROVIDER, DYNAMODB_QUOTA_TABLE, DYNAMODB_RECORDS_TABLE, S3_BUCKET, SQLITE_PATH, UPLOAD_DAILY_LIMIT, UPLOAD_DIR,
)
from .extraction.base import VisionExtractor
from .quota.base import UploadQuota
from .records.base import RecordStore
from .storage.base import FileStorage

# The only module that names concrete implementations: everything else asks for an interface here,
# so switching clouds is one CLOUD_PROVIDER change. Imports sit inside the branches, so the `local`
# provider never loads a cloud SDK. Each getter builds its object once, on first use.


def _not_available_yet(component: str) -> NotImplementedError:
    phase = {"azure": 7}[CLOUD_PROVIDER]
    return NotImplementedError(f"{component} for CLOUD_PROVIDER={CLOUD_PROVIDER!r} arrives in Phase {phase}")


def _required(name: str, value: str) -> str:
    """Return a setting the chosen provider needs, or raise naming it, so a missing one isn't a cryptic SDK error."""
    if not value:
        raise RuntimeError(f"CLOUD_PROVIDER={CLOUD_PROVIDER!r} needs the {name} setting")
    return value


@cache
def get_file_storage() -> FileStorage:
    if CLOUD_PROVIDER == "local":
        from .storage.local import LocalFileStorage
        return LocalFileStorage(UPLOAD_DIR)
    if CLOUD_PROVIDER == "aws":
        from .storage.s3 import S3FileStorage
        return S3FileStorage(_required("S3_BUCKET", S3_BUCKET))
    raise _not_available_yet("FileStorage")


@cache
def get_record_store() -> RecordStore:
    if CLOUD_PROVIDER == "local":
        from .records.local import SQLiteRecordStore
        return SQLiteRecordStore(SQLITE_PATH)
    if CLOUD_PROVIDER == "aws":
        from .records.dynamo import DynamoDBRecordStore
        return DynamoDBRecordStore(_required("DYNAMODB_RECORDS_TABLE", DYNAMODB_RECORDS_TABLE))
    raise _not_available_yet("RecordStore")


@cache
def get_vision_extractor() -> VisionExtractor:
    # `aws` calls the Gemini API too; its key comes from the secret backend (Secrets Manager when deployed)
    if CLOUD_PROVIDER in ("local", "aws"):
        from .extraction.direct_api import GeminiVisionExtractor
        return GeminiVisionExtractor()
    raise _not_available_yet("VisionExtractor")


@cache
def get_upload_quota() -> UploadQuota:
    if CLOUD_PROVIDER == "local":
        from .quota.local import SQLiteUploadQuota
        return SQLiteUploadQuota(SQLITE_PATH, UPLOAD_DAILY_LIMIT)
    if CLOUD_PROVIDER == "aws":
        from .quota.dynamo import DynamoDBUploadQuota
        return DynamoDBUploadQuota(_required("DYNAMODB_QUOTA_TABLE", DYNAMODB_QUOTA_TABLE), UPLOAD_DAILY_LIMIT)
    raise _not_available_yet("UploadQuota")
