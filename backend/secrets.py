import abc
import os
import keyring
from .config import KEYRING_SERVICE_NAME, SECRET_BACKEND, AZURE_KEYVAULT_URL
from .logging_config import setup_logging

logger = setup_logging(__name__)


class SecretProvider(abc.ABC):
    """Abstract base class for secret provider implementations."""

    @abc.abstractmethod
    def get(self, name: str) -> str | None:
        """Retrieve a secret by name.

        Args:
            name: The secret identifier (e.g. 'GROQ_API_KEY').

        Returns:
            str | None: The secret string value if found, else None.
        """
        pass


class KeyringSecretProvider(SecretProvider):
    """Fetches secrets from the local OS Keychain / Credential Manager."""

    def __init__(self, service_name: str | None = None):
        self.service_name = service_name or KEYRING_SERVICE_NAME

    def get(self, name: str) -> str | None:
        try:
            val = keyring.get_password(self.service_name, name)
            return val
        except Exception as e:
            logger.warning(f"[SecretProvider] Failed to read '{name}' from keyring: {e}")
            return None


class EnvSecretProvider(SecretProvider):
    """Fetches secrets from environment variables (fallback)."""

    def get(self, name: str) -> str | None:
        return os.getenv(name)


class CompositeSecretProvider(SecretProvider):
    """Tries primary provider first, then falls back to secondary provider."""

    def __init__(self, primary: SecretProvider, fallback: SecretProvider):
        self.primary = primary
        self.fallback = fallback

    def get(self, name: str) -> str | None:
        val = self.primary.get(name)
        if val is not None and val != "":
            return val
        return self.fallback.get(name)


class AzureKeyVaultSecretProvider(SecretProvider):
    """Fetches secrets from Azure Key Vault using Managed Identity (or local az login)."""

    def __init__(self, vault_url: str | None = None):
        self.vault_url = vault_url or AZURE_KEYVAULT_URL
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self.vault_url:
                logger.warning("[SecretProvider] AZURE_KEYVAULT_URL is empty; Key Vault lookup skipped.")
                return None

            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient
            self._client = SecretClient(
                vault_url=self.vault_url,
                credential=DefaultAzureCredential(),
            )
        return self._client

    def get(self, name: str) -> str | None:
        try:
            client = self._get_client()
            if client is None:
                return None
            # Key Vault secret names cannot contain underscores; convert GROQ_API_KEY -> GROQ-API-KEY
            kv_name = name.replace("_", "-")
            return client.get_secret(kv_name).value
        except Exception as e:
            logger.warning(f"[SecretProvider] Azure Key Vault lookup failed for '{name}': {e}")
            return None


class AWSSecretProvider(SecretProvider):
    """Fetches secrets from AWS Secrets Manager using IAM Role / default credentials."""

    def __init__(self, region_name: str | None = None):
        self.region_name = region_name or os.getenv("AWS_REGION", "us-east-1")
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
                self._client = boto3.client("secretsmanager", region_name=self.region_name)
            except Exception as e:
                logger.warning(f"[SecretProvider] Failed to initialize AWS Secrets Manager client: {e}")
                return None
        return self._client

    def get(self, name: str) -> str | None:
        try:
            client = self._get_client()
            if client is None:
                return None
            response = client.get_secret_value(SecretId=name)
            if "SecretString" in response:
                return response["SecretString"]
            return None
        except Exception as e:
            logger.warning(f"[SecretProvider] AWS Secrets Manager lookup failed for '{name}': {e}")
            return None


_secret_provider_instance: SecretProvider | None = None


def get_secret_provider() -> SecretProvider:
    """Return singleton instance of configured SecretProvider strategy."""
    global _secret_provider_instance
    if _secret_provider_instance is None:
        backend = SECRET_BACKEND.lower()
        service_name = KEYRING_SERVICE_NAME

        if backend == "azure_keyvault":
            _secret_provider_instance = CompositeSecretProvider(
                primary=AzureKeyVaultSecretProvider(),
                fallback=EnvSecretProvider(),
            )
        elif backend == "aws_secretsmanager":
            _secret_provider_instance = CompositeSecretProvider(
                primary=AWSSecretProvider(),
                fallback=EnvSecretProvider(),
            )
        elif backend == "keyring":
            _secret_provider_instance = CompositeSecretProvider(
                primary=KeyringSecretProvider(service_name=service_name),
                fallback=EnvSecretProvider(),
            )
        elif backend == "env":
            _secret_provider_instance = EnvSecretProvider()
        else:
            logger.warning(
                f"[SecretProvider] Unknown SECRET_BACKEND '{backend}', defaulting to Composite(keyring -> env)"
            )
            _secret_provider_instance = CompositeSecretProvider(
                primary=KeyringSecretProvider(service_name=service_name),
                fallback=EnvSecretProvider(),
            )
    return _secret_provider_instance


def get_secret(name: str, default: str | None = None) -> str | None:
    """Retrieve secret by name using the configured strategy.

    Args:
        name: Name of secret (e.g. 'GROQ_API_KEY').
        default: Optional default value if secret is not set anywhere.

    Returns:
        str | None: Secret value or default.
    """
    provider = get_secret_provider()
    val = provider.get(name)
    if val is not None:
        return val
    return default
