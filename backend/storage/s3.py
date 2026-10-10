import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .base import FileStorage, validate_key

# Uploads are at most MAX_UPLOAD_MB; "standard" retries throttling, 5xx and connection errors twice
_CLIENT_CONFIG = Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 3, "mode": "standard"})


class S3FileStorage(FileStorage):
    """Stores files as objects in one S3 bucket (the `aws` provider).

    Credentials and the region come from boto3's usual sources: the Lambda role and AWS_REGION when deployed.
    """

    def __init__(self, bucket: str):
        self.bucket = bucket
        self._s3 = boto3.client("s3", config=_CLIENT_CONFIG)

    def upload(self, key: str, content: bytes) -> str:
        self._s3.put_object(Bucket=self.bucket, Key=validate_key(key), Body=content)
        return key

    def download(self, key: str) -> bytes:
        try:
            response = self._s3.get_object(Bucket=self.bucket, Key=validate_key(key))
        except ClientError as e:
            # S3 answers NoSuchKey only to callers allowed s3:ListBucket; others get AccessDenied for a missing key
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(f"No file stored under key {key!r}") from e
            raise
        return response["Body"].read()
