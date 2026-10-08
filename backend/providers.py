from functools import cache

from .config import CLOUD_PROVIDER, SQLITE_PATH, UPLOAD_DIR
from .extraction.base import VisionExtractor
from .records.base import RecordStore
from .storage.base import FileStorage

# The only module that names concrete implementations: everything else asks for an interface here,
# so switching clouds is one CLOUD_PROVIDER change. Imports sit inside the branches, so the `local`
# provider never loads a cloud SDK. Each getter builds its object once, on first use.


def _not_available_yet(component: str) -> NotImplementedError:
    phase = {"aws": 6, "azure": 7}[CLOUD_PROVIDER]
    return NotImplementedError(f"{component} for CLOUD_PROVIDER={CLOUD_PROVIDER!r} arrives in Phase {phase}")


@cache
def get_file_storage() -> FileStorage:
    if CLOUD_PROVIDER == "local":
        from .storage.local import LocalFileStorage
        return LocalFileStorage(UPLOAD_DIR)
    raise _not_available_yet("FileStorage")


@cache
def get_record_store() -> RecordStore:
    if CLOUD_PROVIDER == "local":
        from .records.local import SQLiteRecordStore
        return SQLiteRecordStore(SQLITE_PATH)
    raise _not_available_yet("RecordStore")


@cache
def get_vision_extractor() -> VisionExtractor:
    if CLOUD_PROVIDER == "local":
        from .extraction.direct_api import GeminiVisionExtractor
        return GeminiVisionExtractor()
    raise _not_available_yet("VisionExtractor")
