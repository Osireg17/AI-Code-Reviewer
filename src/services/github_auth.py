"""GitHub App authentication service."""

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import jwt

from src.config.settings import settings


class GitHubAppAuth:
    """Handle GitHub App authentication and token management."""

    def __init__(self) -> None:
        """Initialize GitHub App authentication."""
        self.app_id = settings.github_app_id
        self.installation_id = settings.github_app_installation_id
        self.private_key = self._load_private_key()

        # Token cache
        self._installation_token: str | None = None
        self._token_expires_at: datetime | None = None

    def _load_private_key(self) -> str:
        """Load the GitHub App private key.

        Returns:
            The private key content

        Raises:
            ValueError: If private key is not configured
        """
        # Try loading from file path first (preferred for local development)
        if settings.github_app_private_key_path:
            key_path = Path(settings.github_app_private_key_path)
            if key_path.exists():
                return key_path.read_text()
            raise ValueError(f"Private key file not found: {key_path}")

        # Fall back to direct key content (useful for production/Railway)
        if settings.github_app_private_key:
            # Validate it's a complete key
            key = settings.github_app_private_key.strip()

            # Check for BEGIN and END markers
            if not (key.startswith("-----BEGIN") and key.endswith("-----")):
                raise ValueError(
                    "GITHUB_APP_PRIVATE_KEY appears incomplete. "
                    "Ensure it includes the full key content with BEGIN/END markers."
                )

            # Check that key has multiple lines (a real key should have content between markers)
            lines = key.split('\n')
            if len(lines) < 3:  # Should have at least BEGIN, content, END
                raise ValueError(
                    "GITHUB_APP_PRIVATE_KEY appears incomplete. "
                    "Ensure it includes the full key content with BEGIN/END markers."
                )

            return key

        raise ValueError(
            "GitHub App private key not configured. "
            "Set GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH"
        )

    def generate_jwt(self) -> str:
        """Generate a JWT for GitHub App authentication.

        The JWT is used to authenticate as the GitHub App itself.
        It's valid for 10 minutes (GitHub's maximum).

        Returns:
            The JWT token

        Raises:
            ValueError: If app_id is not configured
        """
        if not self.app_id:
            raise ValueError("GitHub App ID not configured")

        # Current time with 60 second clock drift protection
        now = int(time.time()) - 60

        # JWT payload
        payload = {
            "iat": now,  # Issued at (60 seconds ago for clock drift)
            "exp": now + (10 * 60),  # Expires in 10 minutes (GitHub max)
            "iss": self.app_id,  # Issuer (GitHub App ID)
        }

        # Generate JWT signed with RS256
        token = jwt.encode(
            payload,
            self.private_key,
            algorithm="RS256",
        )

        return token

    async def get_installation_access_token(self, force_refresh: bool = False) -> str:
        """Get an installation access token.

        This token is used to make API requests on behalf of the app installation.
        Tokens are cached and automatically refreshed when they expire.

        Args:
            force_refresh: Force generation of a new token even if cached token is valid

        Returns:
            The installation access token

        Raises:
            ValueError: If installation_id is not configured
            httpx.HTTPError: If the API request fails
        """
        if not self.installation_id:
            raise ValueError("GitHub App installation ID not configured")

        # Return cached token if still valid
        if not force_refresh and self._is_token_valid():
            return self._installation_token  # type: ignore

        # Generate new JWT
        jwt_token = self.generate_jwt()

        # Request installation access token
        url = f"https://api.github.com/app/installations/{self.installation_id}/access_tokens"

        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {jwt_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers)
            response.raise_for_status()

            data = response.json()

            # Cache the token
            self._installation_token = data["token"]

            # Parse expiration (ISO 8601 format)
            expires_at_str = data["expires_at"]
            self._token_expires_at = datetime.fromisoformat(
                expires_at_str.replace("Z", "+00:00")
            )

            return self._installation_token # type: ignore

    def _is_token_valid(self) -> bool:
        """Check if the cached installation token is still valid.

        Returns:
            True if token exists and hasn't expired (with 5 minute buffer)
        """
        if not self._installation_token or not self._token_expires_at:
            return False

        # Add 5 minute buffer before expiration
        buffer = timedelta(minutes=5)
        now = datetime.now(timezone.utc)

        return now < (self._token_expires_at - buffer)

    async def get_authenticated_client(self) -> httpx.AsyncClient:
        """Get an authenticated HTTP client for GitHub API requests.

        Returns:
            An async HTTP client with authentication headers set

        Example:
            async with auth.get_authenticated_client() as client:
                response = await client.get(
                    "https://api.github.com/repos/owner/repo/pulls/1"
                )
        """
        token = await self.get_installation_access_token()

        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        return httpx.AsyncClient(headers=headers)

    async def create_pr_review(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        body: str,
        event: str = "COMMENT",
        comments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a pull request review.

        Args:
            owner: Repository owner
            repo: Repository name
            pull_number: Pull request number
            body: The body text of the review
            event: The review action (APPROVE, REQUEST_CHANGES, COMMENT)
            comments: Optional inline comments on specific lines

        Returns:
            The created review data

        Raises:
            httpx.HTTPError: If the API request fails

        Example:
            review = await auth.create_pr_review(
                owner="username",
                repo="repo-name",
                pull_number=123,
                body="Great work! Just a few suggestions:",
                event="COMMENT",
                comments=[
                    {
                        "path": "src/file.py",
                        "line": 10,
                        "body": "Consider using a more descriptive name"
                    }
                ]
            )
        """
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}/reviews"

        payload: dict[str, Any] = {
            "body": body,
            "event": event,
        }

        if comments:
            payload["comments"] = comments

        async with await self.get_authenticated_client() as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()


# Global instance
github_app_auth = GitHubAppAuth()
