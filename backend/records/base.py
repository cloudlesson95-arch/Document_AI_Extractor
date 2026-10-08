import abc
import datetime
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from ..extraction.schema import ExtractedReceipt


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class ReceiptRecord(ExtractedReceipt):
    """A stored receipt: the extracted (or corrected) fields plus bookkeeping."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    file_key: str = Field(description="FileStorage key of the original upload")
    mime_type: str = Field(description="Type of the original upload, e.g. application/pdf")
    corrected: bool = Field(default=False, description="True once a person has edited the extracted fields")
    created_at: datetime.datetime = Field(default_factory=_utc_now)
    updated_at: datetime.datetime = Field(default_factory=_utc_now)


# Fields RecordStore.update() may change; the id, the file and the timestamps belong to the store
UPDATABLE_FIELDS = frozenset(ExtractedReceipt.model_fields) | {"corrected"}


class RecordFilters(BaseModel):
    """Search criteria for RecordStore.search(). Bounds are inclusive and unset criteria are ignored.

    A record whose vendor, date or total is null never matches a filter on that field.
    """

    vendor_contains: str | None = None  # case-insensitive substring
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    min_total: Decimal | None = None
    max_total: Decimal | None = None


def apply_update(record: ReceiptRecord, fields: dict) -> ReceiptRecord:
    """Return a validated copy of the record with the given fields changed and updated_at refreshed.

    Shared by every RecordStore so updates are validated the same way everywhere.

    Raises:
        ValueError: If fields names anything outside UPDATABLE_FIELDS.
        pydantic.ValidationError: If a new value is invalid, e.g. a lowercase currency.
    """
    not_updatable = set(fields) - UPDATABLE_FIELDS
    if not_updatable:
        raise ValueError(f"These fields can't be updated: {sorted(not_updatable)}")
    return ReceiptRecord.model_validate({**record.model_dump(), **fields, "updated_at": _utc_now()})


class RecordStore(abc.ABC):
    """Abstract base class for receipt record storage (SQLite, DynamoDB, Table Storage)."""

    @abc.abstractmethod
    def put(self, record: ReceiptRecord) -> str:
        """Save a new record.

        Args:
            record: The record to save; its id must not exist yet.

        Returns:
            str: The record's id.

        Raises:
            ValueError: If a record with the same id already exists.
        """
        pass

    @abc.abstractmethod
    def get(self, record_id: str) -> ReceiptRecord | None:
        """Return the record with this id, or None if there isn't one."""
        pass

    @abc.abstractmethod
    def search(self, filters: RecordFilters | None = None) -> list[ReceiptRecord]:
        """Return the records matching every given filter, newest first; no filters returns all."""
        pass

    @abc.abstractmethod
    def update(self, record_id: str, fields: dict) -> ReceiptRecord | None:
        """Change some fields of a record (see apply_update) and save it.

        Args:
            record_id: Id of the record to change.
            fields: New values, keyed by field name; only UPDATABLE_FIELDS are allowed.

        Returns:
            ReceiptRecord | None: The updated record, or None if there's no record with this id.
        """
        pass
