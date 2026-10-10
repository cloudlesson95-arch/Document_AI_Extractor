import contextlib
import datetime
import sqlite3
from decimal import Decimal

import boto3
import pytest
from pydantic import ValidationError

from backend.records.base import ReceiptRecord, RecordFilters, RecordStore
from backend.records.dynamo import DynamoDBRecordStore
from backend.records.local import SQLiteRecordStore


@pytest.fixture(params=["sqlite", "dynamodb"])
def store(request, tmp_path) -> RecordStore:
    # Every RecordStore must pass the tests that use this fixture; Phase 7 adds Table Storage here
    if request.param == "sqlite":
        return SQLiteRecordStore(tmp_path / "receipts.db")
    if request.param == "dynamodb":
        return DynamoDBRecordStore(request.getfixturevalue("records_table"))  # in moto's DynamoDB, from conftest.py


def make_record(**overrides) -> ReceiptRecord:
    fields = {
        "vendor": "Cafe Uno",
        "date": datetime.date(2026, 9, 14),
        "total_amount": Decimal("9.20"),
        "currency": "EUR",
        "line_items": [{"description": "Latte", "quantity": 2, "unit_price": Decimal("3.75")}],
        "file_key": "receipts/abc.pdf",
        "mime_type": "application/pdf",
    }
    return ReceiptRecord(**{**fields, **overrides})


def at(day: int) -> datetime.datetime:
    return datetime.datetime(2026, 10, day, tzinfo=datetime.timezone.utc)


def vendors(records: list[ReceiptRecord]) -> list[str | None]:
    return [record.vendor for record in records]


def test_put_then_get_returns_an_equal_record(store):
    record = make_record()

    assert store.put(record) == record.id
    assert store.get(record.id) == record  # including exact Decimals, dates and line items


def test_get_of_an_unknown_id_returns_none(store):
    assert store.get("no-such-id") is None


def test_put_rejects_a_duplicate_id(store):
    record = make_record()
    store.put(record)

    with pytest.raises(ValueError):
        store.put(record)


def test_search_without_filters_returns_everything_newest_first(store):
    for day, vendor in [(1, "Oldest"), (3, "Newest"), (2, "Middle")]:
        store.put(make_record(vendor=vendor, created_at=at(day)))

    assert vendors(store.search()) == ["Newest", "Middle", "Oldest"]


@pytest.mark.parametrize("text, expected", [("CAFÉ", ["Café Uno"]), ("o d", ["Pingo Doce"]), ("xyz", [])])
def test_vendor_filter_is_a_case_insensitive_substring(store, text, expected):
    for day, vendor in [(1, "Café Uno"), (2, "Pingo Doce"), (3, None)]:
        store.put(make_record(vendor=vendor, created_at=at(day)))

    assert vendors(store.search(RecordFilters(vendor_contains=text))) == expected


def test_date_range_is_inclusive_and_skips_undated_records(store):
    for day, date in [(1, datetime.date(2026, 9, 1)), (2, datetime.date(2026, 9, 14)), (3, datetime.date(2026, 9, 30)), (4, None)]:
        store.put(make_record(vendor=str(date), date=date, created_at=at(day)))

    found = store.search(RecordFilters(date_from=datetime.date(2026, 9, 14), date_to=datetime.date(2026, 9, 30)))

    assert vendors(found) == ["2026-09-30", "2026-09-14"]


def test_total_range_is_inclusive_and_skips_missing_totals(store):
    for day, total in [(1, Decimal("5.00")), (2, Decimal("9.20")), (3, Decimal("20.00")), (4, None)]:
        store.put(make_record(vendor=str(total), total_amount=total, created_at=at(day)))

    found = store.search(RecordFilters(min_total=Decimal("9.2"), max_total=Decimal("20")))

    assert vendors(found) == ["20.00", "9.20"]


def test_filters_combine(store):
    store.put(make_record(vendor="Cafe Uno", date=datetime.date(2026, 9, 1), created_at=at(1)))
    store.put(make_record(vendor="Cafe Dois", date=datetime.date(2026, 9, 20), created_at=at(2)))
    store.put(make_record(vendor="Pingo Doce", date=datetime.date(2026, 9, 20), created_at=at(3)))

    found = store.search(RecordFilters(vendor_contains="cafe", date_from=datetime.date(2026, 9, 10)))

    assert vendors(found) == ["Cafe Dois"]


def test_update_changes_fields_and_keeps_bookkeeping(store):
    record = make_record()
    store.put(record)

    updated = store.update(record.id, {"vendor": "Café Uno Lisboa", "total_amount": Decimal("9.70"), "corrected": True})

    assert (updated.vendor, updated.total_amount, updated.corrected) == ("Café Uno Lisboa", Decimal("9.70"), True)
    assert (updated.id, updated.file_key, updated.created_at) == (record.id, record.file_key, record.created_at)
    assert updated.updated_at > record.updated_at
    assert store.get(record.id) == updated
    # search sees the new values too
    assert vendors(store.search(RecordFilters(vendor_contains="lisboa", min_total=Decimal("9.5")))) == ["Café Uno Lisboa"]


def test_update_validates_new_values_and_keeps_the_old_record(store):
    record = make_record()
    store.put(record)

    with pytest.raises(ValidationError):
        store.update(record.id, {"currency": "eur"})
    assert store.get(record.id) == record


def test_category_filter_matches_exactly_and_skips_uncategorized_records(store):
    for day, (vendor, category) in enumerate([("Cafe Uno", "Meals"), ("Pingo Doce", "Groceries"), ("Kiosk", None),
                                              ("Cafe Dois", "Meals")], start=1):
        store.put(make_record(vendor=vendor, category=category, created_at=at(day)))

    assert vendors(store.search(RecordFilters(category="Meals"))) == ["Cafe Dois", "Cafe Uno"]
    assert vendors(store.search(RecordFilters(category="Meals", vendor_contains="uno"))) == ["Cafe Uno"]
    assert vendors(store.search(RecordFilters(category="Travel"))) == []


def test_update_changes_the_category_and_its_flag(store):
    record = make_record(category="Groceries")
    store.put(record)

    updated = store.update(record.id, {"category": "Meals", "category_corrected": True})

    assert (updated.category, updated.category_corrected, updated.corrected) == ("Meals", True, False)
    assert vendors(store.search(RecordFilters(category="Meals"))) == ["Cafe Uno"]
    assert store.search(RecordFilters(category="Groceries")) == []


def test_update_refuses_an_unknown_category(store):
    record = make_record()
    store.put(record)

    with pytest.raises(ValidationError):
        store.update(record.id, {"category": "Food"})
    assert store.get(record.id) == record


@pytest.mark.parametrize("field", ["id", "file_key", "mime_type", "created_at", "updated_at"])
def test_update_rejects_bookkeeping_fields(store, field):
    record = make_record()
    store.put(record)

    with pytest.raises(ValueError):
        store.update(record.id, {field: "changed"})


def test_update_of_an_unknown_id_returns_none(store):
    assert store.update("no-such-id", {"vendor": "X"}) is None


def test_sqlite_records_persist_across_store_instances(tmp_path):
    record = make_record()
    SQLiteRecordStore(tmp_path / "receipts.db").put(record)

    assert SQLiteRecordStore(tmp_path / "receipts.db").get(record.id) == record


def test_sqlite_records_saved_before_categories_existed_need_no_migration(tmp_path):
    store = SQLiteRecordStore(tmp_path / "receipts.db")
    record = make_record()
    store.put(record)
    # Rewrite the row the way a database from before categories holds it: without the two new fields
    old_data = record.model_dump_json(exclude={"category", "category_corrected"})
    with contextlib.closing(sqlite3.connect(store.path)) as conn, conn:
        conn.execute("UPDATE receipts SET data = ? WHERE id = ?", (old_data, record.id))

    assert store.get(record.id) == record  # category None, category_corrected False
    assert store.search(RecordFilters(category="Meals")) == []
    store.update(record.id, {"category": "Meals"})
    assert vendors(store.search(RecordFilters(category="Meals"))) == ["Cafe Uno"]


def test_dynamodb_items_hold_the_record_as_json_and_copies_of_its_set_filter_fields(records_table):
    record = make_record(vendor="Café Uno", total_amount=Decimal("12345678901234567.01"), date=None, category="Meals")
    DynamoDBRecordStore(records_table).put(record)

    item = boto3.client("dynamodb").get_item(TableName=records_table, Key={"id": {"S": record.id}})["Item"]

    assert ReceiptRecord.model_validate_json(item["data"]["S"]) == record
    assert item["vendor_search"] == {"S": "café uno"}
    assert item["total_amount"] == {"N": "12345678901234567.01"}  # exact, where a float would round it
    assert item["category"] == {"S": "Meals"}
    assert "date" not in item  # null fields are left out, so no filter on them matches
