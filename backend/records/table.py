import re

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.data.tables import TableErrorCode, UpdateMode

from ..utils.azure_storage import table_service
from .base import ReceiptRecord, RecordFilters, RecordStore, apply_update

# One entity per receipt, all in one partition, with the id as the row key. `data` holds the whole record as JSON; a
# property holds at most 64 KiB (about 32,000 characters, a few hundred line items).
_PARTITION = "receipt"
# Characters Table Storage refuses in a key. The API passes ids from the URL as they are, so get() answers None for an
# id that can't be stored instead of sending it.
_NOT_IN_A_KEY = re.compile(r"[/\\#?\x00-\x1f\x7f-\x9f]")


def _can_be_a_key(record_id: str) -> bool:
    return bool(record_id) and not _NOT_IN_A_KEY.search(record_id) and len(record_id.encode("utf-16-le")) <= 1024


def _matches(record: ReceiptRecord, filters: RecordFilters) -> bool:
    """Whether a record passes every filter that is set, with the other stores' rules: bounds are inclusive, the vendor
    is a case-insensitive substring, and a null field never matches a filter on it."""
    if filters.vendor_contains and not (record.vendor and filters.vendor_contains.casefold() in record.vendor.casefold()):
        return False
    if filters.date_from and not (record.date and record.date >= filters.date_from):
        return False
    if filters.date_to and not (record.date and record.date <= filters.date_to):
        return False
    if filters.min_total is not None and not (record.total_amount is not None and record.total_amount >= filters.min_total):
        return False
    if filters.max_total is not None and not (record.total_amount is not None and record.total_amount <= filters.max_total):
        return False
    return not filters.category or record.category == filters.category


class TableRecordStore(RecordStore):
    """Stores receipt records in one Table Storage table (the `azure` provider).

    Table Storage filters have no substring operator and no exact decimal type, so search() reads every record and
    filters them here, like DynamoDBRecordStore's scan: exact and simple at a demo's size, but every call reads every
    entity. A second table keyed by date is the way to scale it.
    """

    def __init__(self, table: str, account: str = "", connection_string: str = ""):
        self.table = table
        self._table = table_service(account, connection_string).get_table_client(table)

    @staticmethod
    def _entity(record: ReceiptRecord) -> dict:
        return {"PartitionKey": _PARTITION, "RowKey": record.id, "data": record.model_dump_json()}

    def put(self, record: ReceiptRecord) -> str:
        try:
            self._table.create_entity(self._entity(record))
        except ResourceExistsError as e:
            raise ValueError(f"A record with id {record.id!r} already exists") from e
        return record.id

    def get(self, record_id: str) -> ReceiptRecord | None:
        if not _can_be_a_key(record_id):
            return None
        try:
            entity = self._table.get_entity(_PARTITION, record_id, select=["data"])
        except ResourceNotFoundError as e:
            # Only a missing entity is a missing record; a missing table (TableNotFound) is a misconfiguration
            if e.error_code != TableErrorCode.RESOURCE_NOT_FOUND:
                raise
            return None
        return ReceiptRecord.model_validate_json(entity["data"])

    def search(self, filters: RecordFilters | None = None) -> list[ReceiptRecord]:
        filters = filters or RecordFilters()
        entities = self._table.query_entities("PartitionKey eq @partition", parameters={"partition": _PARTITION},
                                              select=["data"])
        records = [ReceiptRecord.model_validate_json(entity["data"]) for entity in entities]
        return sorted((record for record in records if _matches(record, filters)),
                      key=lambda record: record.created_at, reverse=True)

    def update(self, record_id: str, fields: dict) -> ReceiptRecord | None:
        record = self.get(record_id)
        if record is None:
            return None
        updated = apply_update(record, fields)
        self._table.update_entity(self._entity(updated), mode=UpdateMode.REPLACE)  # replaces the whole entity
        return updated
