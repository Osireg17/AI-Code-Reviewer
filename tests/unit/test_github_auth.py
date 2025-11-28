"""Unit tests for GitHub App authentication."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest

from src.services.github_auth import GitHubAppAuth


@pytest.fixture
def mock_settings():
    """Mock settings with GitHub App configuration."""
    with patch("src.services.github_auth.settings") as mock:
        mock.github_app_id = "123456"
        mock.github_app_installation_id = "987654"
        mock.github_app_private_key = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA1234567890...
-----END RSA PRIVATE KEY-----"""
        mock.github_app_private_key_path = None
        yield mock


def test_load_private_key_from_content(mock_settings):
    """Test loading private key from direct content."""
    auth = GitHubAppAuth()
    assert auth.private_key == mock_settings.github_app_private_key


def test_load_private_key_missing():
    """Test error when private key is not configured."""
    with patch("src.services.github_auth.settings") as mock:
        mock.github_app_private_key = None
        mock.github_app_private_key_path = None

        with pytest.raises(ValueError, match="private key not configured"):
            GitHubAppAuth()


def test_generate_jwt(mock_settings):
    """Test JWT generation."""
    auth = GitHubAppAuth()
    token = auth.generate_jwt()

    # Decode without verification to check payload
    decoded = jwt.decode(token, options={"verify_signature": False})

    assert decoded["iss"] == "123456"
    assert "iat" in decoded
    assert "exp" in decoded

    # Check expiration is within 10 minutes
    now = int(time.time())
    assert decoded["exp"] <= now + (10 * 60) + 60  # +60 for clock drift


def test_generate_jwt_no_app_id():
    """Test JWT generation fails without app ID."""
    with patch("src.services.github_auth.settings") as mock:
        mock.github_app_id = None
        mock.github_app_private_key = "fake-key"

        auth = GitHubAppAuth()
        with pytest.raises(ValueError, match="GitHub App ID not configured"):
            auth.generate_jwt()


@pytest.mark.asyncio
async def test_get_installation_access_token(mock_settings):
    """Test getting installation access token."""
    auth = GitHubAppAuth()

    # Mock the HTTP client
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "token": "ghs_test_token",
        "expires_at": "2025-01-01T12:00:00Z",
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )

        token = await auth.get_installation_access_token()

        assert token == "ghs_test_token"
        assert auth._installation_token == "ghs_test_token"
        assert auth._token_expires_at is not None


@pytest.mark.asyncio
async def test_get_installation_access_token_cached(mock_settings):
    """Test that valid cached tokens are reused."""
    auth = GitHubAppAuth()

    # Set a valid cached token
    auth._installation_token = "cached_token"
    auth._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    # Should return cached token without making API call
    token = await auth.get_installation_access_token()
    assert token == "cached_token"


@pytest.mark.asyncio
async def test_get_installation_access_token_no_installation_id():
    """Test error when installation ID is not configured."""
    with patch("src.services.github_auth.settings") as mock:
        mock.github_app_id = "123"
        mock.github_app_installation_id = None
        mock.github_app_private_key = "fake-key"

        auth = GitHubAppAuth()
        with pytest.raises(ValueError, match="installation ID not configured"):
            await auth.get_installation_access_token()


def test_is_token_valid(mock_settings):
    """Test token validity checking."""
    auth = GitHubAppAuth()

    # No token
    assert not auth._is_token_valid()

    # Valid token
    auth._installation_token = "token"
    auth._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    assert auth._is_token_valid()

    # Expired token
    auth._token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert not auth._is_token_valid()

    # Token expiring soon (within 5 minute buffer)
    auth._token_expires_at = datetime.now(timezone.utc) + timedelta(minutes=3)
    assert not auth._is_token_valid()


@pytest.mark.asyncio
async def test_create_pr_review(mock_settings):
    """Test creating a PR review."""
    auth = GitHubAppAuth()

    # Mock the token
    auth._installation_token = "test_token"
    auth._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    # Mock the HTTP client
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "id": 123,
        "body": "Looks good!",
        "state": "COMMENTED",
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )
        mock_client.return_value.__aexit__ = AsyncMock()

        review = await auth.create_pr_review(
            owner="testuser",
            repo="testrepo",
            pull_number=1,
            body="Looks good!",
            event="COMMENT",
        )

        assert review["id"] == 123
        assert review["body"] == "Looks good!"
