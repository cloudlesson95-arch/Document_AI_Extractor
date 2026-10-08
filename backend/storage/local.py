from pathlib import Path

from .base import FileStorage, validate_key


class LocalFileStorage(FileStorage):
    """Stores files on local disk under one root directory (the `local` provider)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / validate_key(key)

    def upload(self, key: str, content: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)  # created on first upload, not at startup
        path.write_bytes(content)
        return key

    def download(self, key: str) -> bytes:
        path = self._path(key)
        # Also covers a key that names a folder: object stores like S3 have no folders to read
        if not path.is_file():
            raise FileNotFoundError(f"No file stored under key {key!r}")
        return path.read_bytes()
