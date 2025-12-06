"""Unit tests for ReviewDependencies model."""

import httpx
import pytest
from github import Github
from pydantic import ValidationError

from src.models.dependencies import ReviewDependencies


class TestReviewDependencies:
    """Test suite for ReviewDependencies model."""

    @pytest.fixture
    def valid_github_client(self) -> Github:
        """Create a valid GitHub client for testing."""
        return Github()

    @pytest.fixture
    def valid_http_client(self) -> httpx.AsyncClient:
        """Create a valid httpx AsyncClient for testing."""
        return httpx.AsyncClient()

    def test_create_valid_review_dependencies(
        self, valid_github_client: Github, valid_http_client: httpx.AsyncClient
    ) -> None:
        """Test creating a valid ReviewDependencies instance."""
        deps = ReviewDependencies(
            github_client=valid_github_client,
            http_client=valid_http_client,
            pr_number=123,
            repo_full_name="owner/repo",
        )

        assert deps.github_client == valid_github_client
        assert deps.http_client == valid_http_client
        assert deps.pr_number == 123
        assert deps.repo_full_name == "owner/repo"

    def test_repo_full_name_with_slash(
        self, valid_github_client: Github, valid_http_client: httpx.AsyncClient
    ) -> None:
        """Test valid repo_full_name formats."""
        valid_names = [
            "owner/repo",
            "Osireg17/AI-Code-Reviewer",
            "facebook/react",
            "microsoft/vscode",
        ]

        for repo_name in valid_names:
            deps = ReviewDependencies(
                github_client=valid_github_client,
                http_client=valid_http_client,
                pr_number=1,
                repo_full_name=repo_name,
            )
            assert deps.repo_full_name == repo_name

    def test_repo_full_name_empty_string(
        self, valid_github_client: Github, valid_http_client: httpx.AsyncClient
    ) -> None:
        """Test that empty repo_full_name raises ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            ReviewDependencies(
                github_client=valid_github_client,
                http_client=valid_http_client,
                pr_number=1,
                repo_full_name="",
            )

        error = exc_info.value
        assert "repo_full_name cannot be empty" in str(error)

    def test_repo_full_name_whitespace_only(
        self, valid_github_client: Github, valid_http_client: httpx.AsyncClient
    ) -> None:
        """Test that whitespace-only repo_full_name raises ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            ReviewDependencies(
                github_client=valid_github_client,
                http_client=valid_http_client,
                pr_number=1,
                repo_full_name="   ",
            )

        error = exc_info.value
        assert "repo_full_name cannot be empty" in str(error)

    def test_repo_full_name_no_slash(
        self, valid_github_client: Github, valid_http_client: httpx.AsyncClient
    ) -> None:
        """Test that repo_full_name without slash raises ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            ReviewDependencies(
                github_client=valid_github_client,
                http_client=valid_http_client,
                pr_number=1,
                repo_full_name="noslash",
            )

        error = exc_info.value
        assert "must be in 'owner/repo' format" in str(error)
        assert "noslash" in str(error)

    def test_repo_full_name_too_many_slashes(
        self, valid_github_client: Github, valid_http_client: httpx.AsyncClient
    ) -> None:
        """Test that repo_full_name with too many slashes raises ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            ReviewDependencies(
                github_client=valid_github_client,
                http_client=valid_http_client,
                pr_number=1,
                repo_full_name="too/many/slashes",
            )

        error = exc_info.value
        assert "must be in 'owner/repo' format" in str(error)

    def test_repo_full_name_empty_owner(
        self, valid_github_client: Github, valid_http_client: httpx.AsyncClient
    ) -> None:
        """Test that repo_full_name with empty owner raises ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            ReviewDependencies(
                github_client=valid_github_client,
                http_client=valid_http_client,
                pr_number=1,
                repo_full_name="/repo",
            )

        error = exc_info.value
        assert "must have non-empty owner and repo parts" in str(error)

    def test_repo_full_name_empty_repo(
        self, valid_github_client: Github, valid_http_client: httpx.AsyncClient
    ) -> None:
        """Test that repo_full_name with empty repo raises ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            ReviewDependencies(
                github_client=valid_github_client,
                http_client=valid_http_client,
                pr_number=1,
                repo_full_name="owner/",
            )

        error = exc_info.value
        assert "must have non-empty owner and repo parts" in str(error)

    def test_pr_number_positive(
        self, valid_github_client: Github, valid_http_client: httpx.AsyncClient
    ) -> None:
        """Test valid positive PR numbers."""
        valid_pr_numbers = [1, 10, 100, 999, 9999]

        for pr_num in valid_pr_numbers:
            deps = ReviewDependencies(
                github_client=valid_github_client,
                http_client=valid_http_client,
                pr_number=pr_num,
                repo_full_name="owner/repo",
            )
            assert deps.pr_number == pr_num

    def test_pr_number_zero(
        self, valid_github_client: Github, valid_http_client: httpx.AsyncClient
    ) -> None:
        """Test that PR number 0 raises ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            ReviewDependencies(
                github_client=valid_github_client,
                http_client=valid_http_client,
                pr_number=0,
                repo_full_name="owner/repo",
            )

        error = exc_info.value
        assert "pr_number must be positive" in str(error)
        assert "got: 0" in str(error)

    def test_pr_number_negative(
        self, valid_github_client: Github, valid_http_client: httpx.AsyncClient
    ) -> None:
        """Test that negative PR numbers raise ValueError."""
        negative_numbers = [-1, -10, -100]

        for pr_num in negative_numbers:
            with pytest.raises(ValidationError) as exc_info:
                ReviewDependencies(
                    github_client=valid_github_client,
                    http_client=valid_http_client,
                    pr_number=pr_num,
                    repo_full_name="owner/repo",
                )

            error = exc_info.value
            assert "pr_number must be positive" in str(error)
            assert f"got: {pr_num}" in str(error)

    def test_arbitrary_types_allowed(
        self, valid_github_client: Github, valid_http_client: httpx.AsyncClient
    ) -> None:
        """Test that Github and httpx.AsyncClient are accepted as arbitrary types."""
        # This test verifies that the model_config allows arbitrary types
        deps = ReviewDependencies(
            github_client=valid_github_client,
            http_client=valid_http_client,
            pr_number=1,
            repo_full_name="owner/repo",
        )

        # Verify the types are preserved
        assert isinstance(deps.github_client, Github)
        assert isinstance(deps.http_client, httpx.AsyncClient)
