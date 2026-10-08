import contextlib
import sqlite3
from pathlib import Path

from .base import ReceiptRecord, RecordFilters, RecordStore, apply_update

# One row per receipt. `data` holds the whole record as JSON and is the source of truth; the other
# columns copy the fields search() filters and sorts on, and are rewritten on every save.
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS receipts (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    vendor_search TEXT,
    date TEXT,
    total_amount REAL,
    data TEXT NOT NULL
)
"""


class SQLiteRecordStore(RecordStore):
    """Stores receipt records in one SQLite table (the `local` provider)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)

    @contextlib.contextmanager
    def _connect(self):
        # A new connection per call: FastAPI serves requests on several threads, and a sqlite3
        # connection can't be shared between threads. `with conn` commits but doesn't close, so
        # close explicitly -- an open connection keeps the file locked on Windows.
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _columns(record: ReceiptRecord) -> dict:
        return {
            "id": record.id,
            "created_at": record.created_at.isoformat(),
            "vendor_search": record.vendor.casefold() if record.vendor else None,
            "date": record.date.isoformat() if record.date else None,
            "total_amount": float(record.total_amount) if record.total_amount is not None else None,
            "data": record.model_dump_json(),
        }

    def put(self, record: ReceiptRecord) -> str:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO receipts (id, created_at, vendor_search, date, total_amount, data) "
                    "VALUES (:id, :created_at, :vendor_search, :date, :total_amount, :data)",
                    self._columns(record),
                )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"A record with id {record.id!r} already exists") from e
        return record.id

    def get(self, record_id: str) -> ReceiptRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM receipts WHERE id = ?", (record_id,)).fetchone()
        return ReceiptRecord.model_validate_json(row[0]) if row else None

    def search(self, filters: RecordFilters | None = None) -> list[ReceiptRecord]:
        filters = filters or RecordFilters()
        conditions, params = [], []
        if filters.vendor_contains:
            conditions.append("instr(vendor_search, ?) > 0")
            params.append(filters.vendor_contains.casefold())
        if filters.date_from:
            conditions.append("date >= ?")
            params.append(filters.date_from.isoformat())
        if filters.date_to:
            conditions.append("date <= ?")
            params.append(filters.date_to.isoformat())
        if filters.min_total is not None:
            conditions.append("total_amount >= ?")
            params.append(float(filters.min_total))
        if filters.max_total is not None:
            conditions.append("total_amount <= ?")
            params.append(float(filters.max_total))
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT data FROM receipts {where} ORDER BY created_at DESC", params).fetchall()
        return [ReceiptRecord.model_validate_json(row[0]) for row in rows]

    def update(self, record_id: str, fields: dict) -> ReceiptRecord | None:
        record = self.get(record_id)
        if record is None:
            return None
        updated = apply_update(record, fields)
        with self._connect() as conn:
            conn.execute(
                "UPDATE receipts SET vendor_search = :vendor_search, date = :date, "
                "total_amount = :total_amount, data = :data WHERE id = :id",
                self._columns(updated),
            )
        return updated
