import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .base import UploadQuota

_CLIENT_CONFIG = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 3, "mode": "standard"})
# A day's count is only read on that day; the table's time to live deletes the item some time after this
_KEEP_DAYS = 7


class DynamoDBUploadQuota(UploadQuota):
    """Counts uploads per day in a DynamoDB table keyed by `day`, a string (the `aws` provider).

    One item per UTC day, with `count` and `expires_at` (epoch seconds) for the table's time to live.
    """

    def __init__(self, table: str, limit: int):
        super().__init__(limit)
        self.table = table
        self._dynamodb = boto3.client("dynamodb", config=_CLIENT_CONFIG)

    def try_acquire(self, day: datetime.date) -> bool:
        expires_at = datetime.datetime.combine(day + datetime.timedelta(days=_KEEP_DAYS), datetime.time(),
                                               datetime.timezone.utc)
        try:
            # A conditional update is atomic, so two instances can't both take the day's last upload.
            # "count" is a reserved word, hence the #placeholders.
            self._dynamodb.update_item(
                TableName=self.table,
                Key={"day": {"S": day.isoformat()}},
                UpdateExpression="SET #expires_at = :expires_at ADD #count :one",
                ConditionExpression="attribute_not_exists(#count) OR #count < :limit",
                ExpressionAttributeNames={"#count": "count", "#expires_at": "expires_at"},
                ExpressionAttributeValues={":one": {"N": "1"}, ":limit": {"N": str(self.limit)},
                                           ":expires_at": {"N": str(int(expires_at.timestamp()))}},
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True
