import os
from unittest.mock import patch, MagicMock

import boto3

from backend.secrets import (
    AWSSecretProvider,
    KeyringSecretProvider,
    EnvSecretProvider,
    CompositeSecretProvider,
    get_secret,
)


def test_env_secret_provider(monkeypatch):
    """Verify EnvSecretProvider retrieves environment variables."""
    monkeypatch.setenv("TEST_ENV_VAR", "env_value_123")
    provider = EnvSecretProvider()
    assert provider.get("TEST_ENV_VAR") == "env_value_123"
    assert provider.get("NON_EXISTENT_VAR") is None


def test_keyring_secret_provider():
    """Verify KeyringSecretProvider calls keyring.get_password with service name."""
    with patch("keyring.get_password") as mock_get_password:
        mock_get_password.return_value = "keyring_value_456"
        provider = KeyringSecretProvider(service_name="test-service")
        
        result = provider.get("TEST_KEY")
        
        assert result == "keyring_value_456"
        mock_get_password.assert_called_once_with("test-service", "TEST_KEY")


def test_composite_secret_provider_primary():
    """Verify CompositeSecretProvider returns primary value when present without calling fallback."""
    primary = MagicMock()
    fallback = MagicMock()
    primary.get.return_value = "primary_secret"
    
    composite = CompositeSecretProvider(primary, fallback)
    result = composite.get("SOME_KEY")
    
    assert result == "primary_secret"
    primary.get.assert_called_once_with("SOME_KEY")
    fallback.get.assert_not_called()


def test_composite_secret_provider_fallback():
    """Verify CompositeSecretProvider falls back to secondary provider when primary is None."""
    primary = MagicMock()
    fallback = MagicMock()
    primary.get.return_value = None
    fallback.get.return_value = "fallback_secret"
    
    composite = CompositeSecretProvider(primary, fallback)
    result = composite.get("SOME_KEY")
    
    assert result == "fallback_secret"
    primary.get.assert_called_once_with("SOME_KEY")
    fallback.get.assert_called_once_with("SOME_KEY")


def test_get_secret_with_default(monkeypatch):
    """Verify get_secret returns default value when secret is not set anywhere."""
    monkeypatch.delenv("UNSET_SECRET_XYZ", raising=False)
    with patch("keyring.get_password", return_value=None):
        result = get_secret("UNSET_SECRET_XYZ", default="my_default")
        assert result == "my_default"


def test_aws_secret_provider_reads_the_app_prefixed_secret(aws):
    """Verify AWSSecretProvider reads document-ai-extractor/<name> from Secrets Manager (moto, from conftest.py)."""
    secrets = boto3.client("secretsmanager")
    secrets.create_secret(Name="document-ai-extractor/GOOGLE_API_KEY", SecretString="app-key")
    secrets.create_secret(Name="GOOGLE_API_KEY", SecretString="another-app-key")

    provider = AWSSecretProvider()

    assert provider.get("GOOGLE_API_KEY") == "app-key"
    assert provider.get("GROQ_API_KEY") is None  # missing: logged, and the composite falls back to the environment
