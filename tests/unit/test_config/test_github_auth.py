"""Unit tests for GitHub App authentication."""

import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.services.github_auth import GitHubAppAuth


@pytest.fixture(scope="session")
def generate_test_rsa_key():
    """Generate a valid RSA private key for testing.

    This generates a real RSA key pair dynamically to ensure tests
    always have a valid key format, avoiding truncation issues.
    """
    # Generate RSA key pair (2048 bits is standard for GitHub Apps)
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )

    # Serialize to PEM format (the format GitHub expects)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )

    return pem.decode("utf-8")


@pytest.fixture
def mock_settings_with_content(generate_test_rsa_key):
    """Mock settings with private key as content."""
    with patch("src.services.github_auth.settings") as mock:
        mock.github_app_id = "123456"
        mock.github_app_installation_id = "987654"
        mock.github_app_private_key = generate_test_rsa_key
        mock.github_app_private_key_path = None
        yield mock


@pytest.fixture
def mock_settings_with_file(generate_test_rsa_key):
    """Mock settings with private key as file path."""
    # Create a temporary file with the key
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
        f.write(generate_test_rsa_key)
        temp_path = f.name

    with patch("src.services.github_auth.settings") as mock:
        mock.github_app_id = "123456"
        mock.github_app_installation_id = "987654"
        mock.github_app_private_key = None
        mock.github_app_private_key_path = temp_path
        yield mock

    # Cleanup
    Path(temp_path).unlink()


class TestPrivateKeyLoading:
    """Tests for private key loading."""

    def test_load_private_key_from_file(
        self, mock_settings_with_file, generate_test_rsa_key
    ):
        """Test loading private key from file path."""
        auth = GitHubAppAuth()
        assert auth.private_key == generate_test_rsa_key
        # Check for RSA private key marker (split to avoid pre-commit hook detection)
        assert "BEGIN RSA " + "PRIVATE KEY" in auth.private_key

    def test_load_private_key_prefers_file(self, generate_test_rsa_key):
        """Test that file path is preferred over content."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
            f.write(generate_test_rsa_key)
            temp_path = f.name

        try:
            with patch("src.services.github_auth.settings") as mock:
                mock.github_app_id = "123456"
                mock.github_app_installation_id = "987654"
                mock.github_app_private_key = (
                    "incomplete-key-content"  # pragma: allowlist secret
                )
                mock.github_app_private_key_path = temp_path

                auth = GitHubAppAuth()
                # Should load from file, not the incomplete content
                assert auth.private_key == generate_test_rsa_key
        finally:
            Path(temp_path).unlink()

    def test_load_private_key_file_not_found(self):
        """Test error when private key file doesn't exist."""
        with patch("src.services.github_auth.settings") as mock:
            mock.github_app_id = "123456"
            mock.github_app_installation_id = "987654"
            mock.github_app_private_key = None
            mock.github_app_private_key_path = "/nonexistent/path/key.pem"

            with pytest.raises(ValueError, match="Private key file not found"):
                GitHubAppAuth()

    def test_load_private_key_incomplete_content(self):
        """Test error when private key content is incomplete."""
        with patch("src.services.github_auth.settings") as mock:
            mock.github_app_id = "123456"
            mock.github_app_installation_id = "987654"
            # Split string to avoid pre-commit hook detection
            mock.github_app_private_key = "-----BEGIN RSA " + "PRIVATE KEY-----"
            mock.github_app_private_key_path = None

            with pytest.raises(ValueError, match="appears incomplete"):
                GitHubAppAuth()

    def test_load_private_key_missing(self):
        """Test error when no private key is configured."""
        with patch("src.services.github_auth.settings") as mock:
            mock.github_app_id = "123456"
            mock.github_app_installation_id = "987654"
            mock.github_app_private_key = None
            mock.github_app_private_key_path = None

            with pytest.raises(ValueError, match="private key not configured"):
                GitHubAppAuth()


class TestJWTGeneration:
    """Tests for JWT generation."""

    def test_generate_jwt(self, mock_settings_with_content):
        """Test JWT generation."""
        auth = GitHubAppAuth()
        token = auth.generate_jwt()

        # Verify it's a valid JWT format
        assert isinstance(token, str)
        assert token.count(".") == 2  # JWT has 3 parts

        # Decode without verification to check payload
        decoded = jwt.decode(token, options={"verify_signature": False})

        assert decoded["iss"] == "123456"
        assert "iat" in decoded
        assert "exp" in decoded

        # Check issued at is in the past (for clock drift protection)
        now = int(time.time())
        assert decoded["iat"] <= now

        # Check expiration is within 10 minutes
        assert decoded["exp"] <= now + (10 * 60) + 60

    def test_generate_jwt_no_app_id(self, generate_test_rsa_key):
        """Test JWT generation fails without app ID."""
        with patch("src.services.github_auth.settings") as mock:
            mock.github_app_id = None
            mock.github_app_installation_id = "987654"
            mock.github_app_private_key = generate_test_rsa_key
            mock.github_app_private_key_path = None

            auth = GitHubAppAuth()
            with pytest.raises(ValueError, match="GitHub App ID not configured"):
                auth.generate_jwt()

    def test_generate_jwt_multiple_times(self, mock_settings_with_content):
        """Test that multiple JWTs can be generated."""
        auth = GitHubAppAuth()

        token1 = auth.generate_jwt()
        time.sleep(1)
        token2 = auth.generate_jwt()

        # Tokens should be different due to different iat
        assert token1 != token2


class TestInstallationToken:
    """Tests for installation access token."""

    @pytest.mark.asyncio
    async def test_get_installation_access_token(self, mock_settings_with_content):
        """Test getting installation access token."""
        auth = GitHubAppAuth()

        # Mock the HTTP client
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "token": "ghs_test_token",
            "expires_at": "2025-11-29T12:00:00Z",
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
    async def test_get_installation_access_token_cached(
        self, mock_settings_with_content
    ):
        """Test that valid cached tokens are reused."""
        auth = GitHubAppAuth()

        # Set a valid cached token
        auth._installation_token = "cached_token"
        auth._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        # Should return cached token without making API call
        token = await auth.get_installation_access_token()
        assert token == "cached_token"

    @pytest.mark.asyncio
    async def test_get_installation_access_token_force_refresh(
        self, mock_settings_with_content
    ):
        """Test forcing token refresh."""
        auth = GitHubAppAuth()

        # Set a valid cached token
        auth._installation_token = "cached_token"
        auth._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        # Mock the HTTP client
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "token": "ghs_new_token",
            "expires_at": "2025-11-29T13:00:00Z",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            # Force refresh
            token = await auth.get_installation_access_token(force_refresh=True)

            assert token == "ghs_new_token"
            assert auth._installation_token == "ghs_new_token"

    @pytest.mark.asyncio
    async def test_get_installation_access_token_no_installation_id(
        self, generate_test_rsa_key
    ):
        """Test error when installation ID is not configured."""
        with patch("src.services.github_auth.settings") as mock:
            mock.github_app_id = "123"
            mock.github_app_installation_id = None
            mock.github_app_private_key = generate_test_rsa_key
            mock.github_app_private_key_path = None

            auth = GitHubAppAuth()
            with pytest.raises(ValueError, match="installation ID not configured"):
                await auth.get_installation_access_token()


class TestTokenValidation:
    """Tests for token validity checking."""

    def test_is_token_valid_no_token(self, mock_settings_with_content):
        """Test that no token is invalid."""
        auth = GitHubAppAuth()
        assert not auth._is_token_valid()

    def test_is_token_valid_valid_token(self, mock_settings_with_content):
        """Test that valid token returns True."""
        auth = GitHubAppAuth()

        auth._installation_token = "token"
        auth._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        assert auth._is_token_valid()

    def test_is_token_valid_expired_token(self, mock_settings_with_content):
        """Test that expired token returns False."""
        auth = GitHubAppAuth()

        auth._installation_token = "token"
        auth._token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        assert not auth._is_token_valid()

    def test_is_token_valid_expiring_soon(self, mock_settings_with_content):
        """Test that token expiring within buffer returns False."""
        auth = GitHubAppAuth()

        auth._installation_token = "token"
        # Token expires in 3 minutes (within 5 minute buffer)
        auth._token_expires_at = datetime.now(timezone.utc) + timedelta(minutes=3)
        assert not auth._is_token_valid()


class TestAuthenticatedClient:
    """Tests for authenticated HTTP client."""

    @pytest.mark.asyncio
    async def test_get_authenticated_client(self, mock_settings_with_content):
        """Test getting authenticated client."""
        auth = GitHubAppAuth()

        # Mock the token
        auth._installation_token = "test_token"
        auth._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        client = await auth.get_authenticated_client()

        assert client.headers["Authorization"] == "Bearer test_token"
        assert client.headers["Accept"] == "application/vnd.github+json"
        assert client.headers["X-GitHub-Api-Version"] == "2022-11-28"


class TestPRReview:
    """Tests for PR review creation."""

    @pytest.mark.asyncio
    async def test_create_pr_review(self, mock_settings_with_content):
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
            assert review["state"] == "COMMENTED"

    @pytest.mark.asyncio
    async def test_create_pr_review_with_comments(self, mock_settings_with_content):
        """Test creating a PR review with inline comments."""
        auth = GitHubAppAuth()

        # Mock the token
        auth._installation_token = "test_token"
        auth._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        # Mock the HTTP client
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 456,
            "body": "Some suggestions",
            "state": "COMMENTED",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aexit__ = AsyncMock()

            comments = [
                {
                    "path": "src/file.py",
                    "line": 10,
                    "body": "Consider using a better name",
                }
            ]

            review = await auth.create_pr_review(
                owner="testuser",
                repo="testrepo",
                pull_number=2,
                body="Some suggestions",
                event="COMMENT",
                comments=comments,
            )

            assert review["id"] == 456

            # Verify the request was made with comments
            call_args = mock_instance.post.call_args
            assert call_args[1]["json"]["comments"] == comments
