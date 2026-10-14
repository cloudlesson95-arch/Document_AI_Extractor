import datetime

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.data.tables import TableErrorCode, UpdateMode

from ..utils.azure_storage import table_service
from .base import UploadQuota

_PARTITION = "day"
# An attempt fails only when another instance counted an upload in between, so this bounds how many uploads may race
# for the same day. The per-minute rate limit keeps that far lower.
_MAX_ATTEMPTS = 25


class TableUploadQuota(UploadQuota):
    """Counts uploads per UTC day in a Table Storage table (the `azure` provider).

    One entity per day, with the date (YYYY-MM-DD) as its row key and `count`. Table Storage has no time to live, so
    past days stay, at a few bytes each.
    """

    def __init__(self, table: str, limit: int, account: str = "", connection_string: str = ""):
        super().__init__(limit)
        self.table = table
        self._table = table_service(account, connection_string).get_table_client(table)

    def try_acquire(self, day: datetime.date) -> bool:
        key = day.isoformat()
        # Table Storage has no atomic increment, so the count is read, then written back one higher only if the entity
        # hasn't changed since (its ETag). If another instance wrote in between, the write fails and the loop reads again.
        for _ in range(_MAX_ATTEMPTS):
            try:
                entity = self._table.get_entity(_PARTITION, key)
            except ResourceNotFoundError as e:
                if e.error_code != TableErrorCode.RESOURCE_NOT_FOUND:  # a missing table is a misconfiguration
                    raise
                try:
                    self._table.create_entity({"PartitionKey": _PARTITION, "RowKey": key, "count": 1})
                    return True
                except ResourceExistsError:
                    continue  # another instance counted the day's first upload in between
            if entity["count"] >= self.limit:
                return False
            try:
                self._table.update_entity({"PartitionKey": _PARTITION, "RowKey": key, "count": entity["count"] + 1},
                                          mode=UpdateMode.REPLACE, etag=entity.metadata["etag"],
                                          match_condition=MatchConditions.IfNotModified)
                return True
            except ResourceModifiedError:
                continue  # another instance counted an upload in between
        raise RuntimeError(f"[UploadQuota] Couldn't count the upload in {_MAX_ATTEMPTS} attempts: too many at once")
