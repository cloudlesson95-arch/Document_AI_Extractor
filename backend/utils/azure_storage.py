from functools import cache

from azure.data.tables import TableServiceClient
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ExponentialRetry

# Clients for the `azure` provider's Storage account, shared by Blob Storage and Table Storage. The SDKs' defaults retry
# for minutes (Blob: 15, 18 and 24 s backoffs on 60 s reads; Tables: up to 10 retries), longer than a request may take,
# so these match the AWS clients: short connects and two quick retries.
_BLOB_OPTIONS = {"connection_timeout": 5, "read_timeout": 30,
                 "retry_policy": ExponentialRetry(initial_backoff=1, increment_base=2, retry_total=2)}
_TABLE_OPTIONS = {"connection_timeout": 5, "read_timeout": 10, "retry_total": 2}


@cache
def credential() -> DefaultAzureCredential:
    """The app's identity: the Container App's managed identity (AZURE_CLIENT_ID names it), or `az login` locally.

    One credential for both clients, so they share its cached access token.
    """
    return DefaultAzureCredential()


def blob_service(account: str = "", connection_string: str = "") -> BlobServiceClient:
    """Blob Storage of the account, or of Azurite (the storage emulator) when a connection string is given."""
    if connection_string:
        return BlobServiceClient.from_connection_string(connection_string, **_BLOB_OPTIONS)
    return BlobServiceClient(f"https://{account}.blob.core.windows.net", credential=credential(), **_BLOB_OPTIONS)


def table_service(account: str = "", connection_string: str = "") -> TableServiceClient:
    """Table Storage of the account, or of Azurite (the storage emulator) when a connection string is given."""
    if connection_string:
        return TableServiceClient.from_connection_string(connection_string, **_TABLE_OPTIONS)
    return TableServiceClient(f"https://{account}.table.core.windows.net", credential=credential(), **_TABLE_OPTIONS)
