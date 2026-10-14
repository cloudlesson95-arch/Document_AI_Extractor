import datetime
import threading

import boto3
import pytest

from backend.quota.dynamo import DynamoDBUploadQuota
from backend.quota.local import SQLiteUploadQuota
from backend.quota.table import TableUploadQuota

DAY = datetime.date(2026, 10, 10)


@pytest.fixture(params=["sqlite", "dynamodb", "table"])
def make_quota(request, tmp_path):
    """Builds an UploadQuota with a given limit. Every implementation must pass these tests."""
    if request.param == "sqlite":
        return lambda limit: SQLiteUploadQuota(tmp_path / "receipts.db", limit)
    if request.param == "dynamodb":
        table = request.getfixturevalue("quota_table")  # in moto's DynamoDB, from conftest.py
        return lambda limit: DynamoDBUploadQuota(table, limit)
    if request.param == "table":
        table, azurite = request.getfixturevalue("azure_table"), request.getfixturevalue("azurite")  # from conftest.py
        return lambda limit: TableUploadQuota(table, limit, connection_string=azurite)


def test_allows_uploads_up_to_the_limit_then_refuses(make_quota):
    quota = make_quota(3)

    assert [quota.try_acquire(DAY) for _ in range(5)] == [True, True, True, False, False]


def test_each_day_has_its_own_count(make_quota):
    quota = make_quota(1)

    assert quota.try_acquire(DAY)
    assert not quota.try_acquire(DAY)
    assert quota.try_acquire(DAY + datetime.timedelta(days=1))


def test_every_instance_shares_the_count(make_quota):
    # Each Lambda instance or worker process builds its own quota object over the same storage
    first, second = make_quota(2), make_quota(2)

    assert [first.try_acquire(DAY), second.try_acquire(DAY), first.try_acquire(DAY)] == [True, True, False]


def test_a_limit_below_one_is_refused(make_quota):
    with pytest.raises(ValueError):
        make_quota(0)


def test_sqlite_counts_concurrent_uploads_exactly(tmp_path):
    # DynamoDB's atomic conditional update is the service's guarantee, which moto can't demonstrate; SQLite's is ours
    quota = SQLiteUploadQuota(tmp_path / "receipts.db", 5)
    results = []
    threads = [threading.Thread(target=lambda: results.append(quota.try_acquire(DAY))) for _ in range(20)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [False] * 15 + [True] * 5


def test_dynamodb_counts_expire_a_week_after_their_day(quota_table):
    DynamoDBUploadQuota(quota_table, 5).try_acquire(DAY)

    item = boto3.client("dynamodb").get_item(TableName=quota_table, Key={"day": {"S": "2026-10-10"}})["Item"]

    assert item["count"] == {"N": "1"}
    expires = datetime.datetime.fromtimestamp(int(item["expires_at"]["N"]), datetime.timezone.utc)
    assert expires == datetime.datetime(2026, 10, 17, tzinfo=datetime.timezone.utc)


@pytest.mark.parametrize("limit, allowed", [(5, 5), (50, 20)])
def test_table_storage_counts_concurrent_uploads_exactly(azurite, azure_table, limit, allowed):
    # Table Storage has no atomic increment: TableUploadQuota writes only over the count it read (its ETag) and retries
    # when another instance wrote first. Under the limit, every racing upload must still get through.
    quota = TableUploadQuota(azure_table, limit, connection_string=azurite)
    results = []
    threads = [threading.Thread(target=lambda: results.append(quota.try_acquire(DAY))) for _ in range(20)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [False] * (20 - allowed) + [True] * allowed
