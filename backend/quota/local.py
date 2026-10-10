import contextlib
import datetime
import sqlite3
from pathlib import Path

from .base import UploadQuota

_CREATE_TABLE = "CREATE TABLE IF NOT EXISTS upload_counts (day TEXT PRIMARY KEY, count INTEGER NOT NULL)"
# One statement, so the check and the count are atomic: it inserts the day's first upload, or adds one while the
# count is under the limit, and changes no row once the limit is reached
_COUNT_UPLOAD = (
    "INSERT INTO upload_counts (day, count) VALUES (:day, 1) "
    "ON CONFLICT (day) DO UPDATE SET count = count + 1 WHERE count < :limit"
)


class SQLiteUploadQuota(UploadQuota):
    """Counts uploads per day in a table of the local SQLite database (the `local` provider)."""

    def __init__(self, path: Path, limit: int):
        super().__init__(limit)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn, conn:
            conn.execute(_CREATE_TABLE)

    def _connect(self):
        # A new connection per call, closed afterwards, for the same reasons as SQLiteRecordStore._connect
        return contextlib.closing(sqlite3.connect(self.path))

    def try_acquire(self, day: datetime.date) -> bool:
        with self._connect() as conn, conn:
            cursor = conn.execute(_COUNT_UPLOAD, {"day": day.isoformat(), "limit": self.limit})
        return cursor.rowcount == 1
