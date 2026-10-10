import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .base import ReceiptRecord, RecordFilters, RecordStore, apply_update

# One item per receipt in a table whose only key is `id` (a string). `data` holds the whole record as JSON and is the
# source of truth; the other attributes copy the fields search() filters on, and are rewritten on every save. A field
# that is null is left out, so a filter on it never matches, like NULL in the SQLite store.
_CLIENT_CONFIG = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 3, "mode": "standard"})


class DynamoDBRecordStore(RecordStore):
    """Stores receipt records in one DynamoDB table (the `aws` provider).

    search() scans the whole table and sorts in memory: exact and simple at a demo's size, but every call reads every
    item. A global secondary index on created_at is the way to scale it.
    """

    def __init__(self, table: str):
        self.table = table
        self._dynamodb = boto3.client("dynamodb", config=_CLIENT_CONFIG)

    @staticmethod
    def _item(record: ReceiptRecord) -> dict:
        item = {"id": {"S": record.id}, "data": {"S": record.model_dump_json()}}
        if record.vendor:
            item["vendor_search"] = {"S": record.vendor.casefold()}
        if record.date:
            item["date"] = {"S": record.date.isoformat()}
        if record.total_amount is not None:
            item["total_amount"] = {"N": str(record.total_amount)}  # DynamoDB numbers are exact decimals
        if record.category:
            item["category"] = {"S": record.category}
        return item

    def put(self, record: ReceiptRecord) -> str:
        try:
            self._dynamodb.put_item(TableName=self.table, Item=self._item(record),
                                    ConditionExpression="attribute_not_exists(#id)", ExpressionAttributeNames={"#id": "id"})
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError(f"A record with id {record.id!r} already exists") from e
            raise
        return record.id

    def get(self, record_id: str) -> ReceiptRecord | None:
        # Strongly consistent reads here and in search(), so a saved record shows up at once
        item = self._dynamodb.get_item(TableName=self.table, Key={"id": {"S": record_id}}, ConsistentRead=True).get("Item")
        return ReceiptRecord.model_validate_json(item["data"]["S"]) if item else None

    def search(self, filters: RecordFilters | None = None) -> list[ReceiptRecord]:
        filters = filters or RecordFilters()
        criteria = []  # (attribute, operator, value) for each filter that is set
        if filters.vendor_contains:
            criteria.append(("vendor_search", "contains", {"S": filters.vendor_contains.casefold()}))
        if filters.date_from:
            criteria.append(("date", ">=", {"S": filters.date_from.isoformat()}))
        if filters.date_to:
            criteria.append(("date", "<=", {"S": filters.date_to.isoformat()}))
        if filters.min_total is not None:
            criteria.append(("total_amount", ">=", {"N": str(filters.min_total)}))
        if filters.max_total is not None:
            criteria.append(("total_amount", "<=", {"N": str(filters.max_total)}))
        if filters.category:
            criteria.append(("category", "=", {"S": filters.category}))

        # Names go through #placeholders ("date" and "data" are reserved words) and values through :v0, :v1, ...;
        # DynamoDB refuses placeholders an expression doesn't use, so only the criteria's are sent
        conditions = [f"contains(#{attribute}, :v{i})" if operator == "contains" else f"#{attribute} {operator} :v{i}"
                      for i, (attribute, operator, _) in enumerate(criteria)]
        scan = {"TableName": self.table, "ProjectionExpression": "#data", "ConsistentRead": True,
                "ExpressionAttributeNames": {"#data": "data"} | {f"#{attribute}": attribute for attribute, _, _ in criteria}}
        if criteria:
            scan |= {"FilterExpression": " AND ".join(conditions),
                     "ExpressionAttributeValues": {f":v{i}": value for i, (_, _, value) in enumerate(criteria)}}
        pages = self._dynamodb.get_paginator("scan").paginate(**scan)
        records = [ReceiptRecord.model_validate_json(item["data"]["S"]) for page in pages for item in page["Items"]]
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def update(self, record_id: str, fields: dict) -> ReceiptRecord | None:
        record = self.get(record_id)
        if record is None:
            return None
        updated = apply_update(record, fields)
        self._dynamodb.put_item(TableName=self.table, Item=self._item(updated))  # replaces the whole item
        return updated
