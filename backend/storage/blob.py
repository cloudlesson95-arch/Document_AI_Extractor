from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import StorageErrorCode

from ..utils.azure_storage import blob_service
from .base import FileStorage, validate_key


class BlobFileStorage(FileStorage):
    """Stores files as blobs in one Blob Storage container (the `azure` provider).

    Signs in with the app's managed identity, or uses a connection string for Azurite (the storage emulator).
    """

    def __init__(self, container: str, account: str = "", connection_string: str = ""):
        self.container = container
        self._container = blob_service(account, connection_string).get_container_client(container)

    def upload(self, key: str, content: bytes) -> str:
        self._container.upload_blob(validate_key(key), content, overwrite=True)
        return key

    def download(self, key: str) -> bytes:
        try:
            return self._container.download_blob(validate_key(key)).readall()
        except ResourceNotFoundError as e:
            # Only a missing blob is a missing file; a missing container (ContainerNotFound) is a misconfiguration
            if e.error_code != StorageErrorCode.BLOB_NOT_FOUND:
                raise
            raise FileNotFoundError(f"No file stored under key {key!r}") from e
