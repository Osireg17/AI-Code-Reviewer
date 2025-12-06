"""Tests for GitHub tools."""

from unittest.mock import Mock

import httpx
import pytest
from github import Github, GithubException
from pydantic_ai import RunContext

from src.models.dependencies import ReviewDependencies
from src.tools.github_tools import (
    fetch_pr_context,
    get_file_diff,
    get_full_file,
    list_changed_files,
    post_review_comment,
    post_summary_comment,
)


@pytest.fixture
def mock_deps():
    """Create mock ReviewDependencies."""
    github_client = Mock(spec=Github)
    http_client = Mock(spec=httpx.AsyncClient)

    deps = ReviewDependencies(
        github_client=github_client,
        http_client=http_client,
        pr_number=123,
        repo_full_name="owner/repo",
    )
    return deps


@pytest.fixture
def mock_ctx(mock_deps):
    """Create mock RunContext with ReviewDependencies."""
    ctx = Mock(spec=RunContext)
    ctx.deps = mock_deps
    return ctx


class TestFetchPRContext:
    """Tests for fetch_pr_context()."""

    @pytest.mark.asyncio
    async def test_fetch_pr_context_success(self, mock_ctx):
        """Test successful PR context fetching."""
        # Setup mocks
        mock_repo = Mock()
        mock_pr = Mock()
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_label = Mock()
        mock_label.name = "bug"
        mock_base = Mock()
        mock_base.ref = "main"
        mock_head = Mock()
        mock_head.ref = "feature-branch"

        mock_pr.number = 123
        mock_pr.title = "Test PR"
        mock_pr.body = "Test description"
        mock_pr.user = mock_user
        mock_pr.changed_files = 5
        mock_pr.additions = 100
        mock_pr.deletions = 50
        mock_pr.commits = 3
        mock_pr.labels = [mock_label]
        mock_pr.base = mock_base
        mock_pr.head = mock_head

        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        # Execute
        result = await fetch_pr_context(mock_ctx)

        # Assert
        assert result["number"] == 123
        assert result["title"] == "Test PR"
        assert result["description"] == "Test description"
        assert result["author"] == "testuser"
        assert result["files_changed"] == 5
        assert result["additions"] == 100
        assert result["deletions"] == 50
        assert result["commits"] == 3
        assert result["labels"] == ["bug"]
        assert result["base_branch"] == "main"
        assert result["head_branch"] == "feature-branch"

    @pytest.mark.asyncio
    async def test_fetch_pr_context_github_error(self, mock_ctx):
        """Test PR context fetching with GitHub API error."""
        mock_ctx.deps.github_client.get_repo.side_effect = GithubException(
            404, "Not Found", None
        )

        result = await fetch_pr_context(mock_ctx)

        assert "error" in result
        assert "GitHub API error" in result["error"]

    @pytest.mark.asyncio
    async def test_fetch_pr_context_empty_body(self, mock_ctx):
        """Test PR context with None body."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_user = Mock()
        mock_user.login = "testuser"
        mock_base = Mock()
        mock_base.ref = "main"
        mock_head = Mock()
        mock_head.ref = "feature"

        mock_pr.number = 123
        mock_pr.title = "Test"
        mock_pr.body = None  # Test None handling
        mock_pr.user = mock_user
        mock_pr.changed_files = 1
        mock_pr.additions = 10
        mock_pr.deletions = 5
        mock_pr.commits = 1
        mock_pr.labels = []
        mock_pr.base = mock_base
        mock_pr.head = mock_head

        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await fetch_pr_context(mock_ctx)

        assert result["description"] == ""  # Should default to empty string


class TestListChangedFiles:
    """Tests for list_changed_files()."""

    @pytest.mark.asyncio
    async def test_list_changed_files_success(self, mock_ctx):
        """Test successful file listing."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_file1 = Mock()
        mock_file1.filename = "src/file1.py"
        mock_file2 = Mock()
        mock_file2.filename = "tests/test_file1.py"

        mock_pr.get_files.return_value = [mock_file1, mock_file2]
        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await list_changed_files(mock_ctx)

        assert result == ["src/file1.py", "tests/test_file1.py"]

    @pytest.mark.asyncio
    async def test_list_changed_files_error(self, mock_ctx):
        """Test file listing with error."""
        mock_ctx.deps.github_client.get_repo.side_effect = Exception("API Error")

        result = await list_changed_files(mock_ctx)

        assert len(result) == 1
        assert "Error" in result[0]


class TestGetFileDiff:
    """Tests for get_file_diff()."""

    @pytest.mark.asyncio
    async def test_get_file_diff_success(self, mock_ctx):
        """Test successful file diff retrieval."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_file = Mock()
        mock_file.filename = "src/test.py"
        mock_file.status = "modified"
        mock_file.additions = 10
        mock_file.deletions = 5
        mock_file.changes = 15
        mock_file.patch = "@@ -1,3 +1,3 @@\n-old\n+new"
        mock_file.previous_filename = None

        mock_pr.get_files.return_value = [mock_file]
        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await get_file_diff(mock_ctx, "src/test.py")

        assert result["filename"] == "src/test.py"
        assert result["status"] == "modified"
        assert result["additions"] == 10
        assert result["deletions"] == 5
        assert result["changes"] == 15
        assert "@@ -1,3 +1,3 @@" in result["patch"]

    @pytest.mark.asyncio
    async def test_get_file_diff_file_not_found(self, mock_ctx):
        """Test file diff when file doesn't exist."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_file = Mock()
        mock_file.filename = "other.py"

        mock_pr.get_files.return_value = [mock_file]
        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await get_file_diff(mock_ctx, "nonexistent.py")

        assert "error" in result
        assert "File not found" in result["error"]

    @pytest.mark.asyncio
    async def test_get_file_diff_renamed_file(self, mock_ctx):
        """Test file diff for renamed file."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_file = Mock()
        mock_file.filename = "new_name.py"
        mock_file.status = "renamed"
        mock_file.additions = 0
        mock_file.deletions = 0
        mock_file.changes = 0
        mock_file.patch = ""
        mock_file.previous_filename = "old_name.py"

        mock_pr.get_files.return_value = [mock_file]
        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await get_file_diff(mock_ctx, "new_name.py")

        assert result["status"] == "renamed"
        assert result["previous_filename"] == "old_name.py"


class TestGetFullFile:
    """Tests for get_full_file()."""

    @pytest.mark.asyncio
    async def test_get_full_file_head_success(self, mock_ctx):
        """Test successful file content retrieval at head."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_head = Mock()
        mock_head.sha = "abc123"
        mock_pr.head = mock_head

        mock_content = Mock()
        mock_content.decoded_content = b"print('hello')"

        mock_repo.get_contents.return_value = mock_content
        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await get_full_file(mock_ctx, "test.py", "head")

        assert result == "print('hello')"
        mock_repo.get_contents.assert_called_with("test.py", ref="abc123")

    @pytest.mark.asyncio
    async def test_get_full_file_base_success(self, mock_ctx):
        """Test successful file content retrieval at base."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_base = Mock()
        mock_base.sha = "def456"
        mock_pr.base = mock_base

        mock_content = Mock()
        mock_content.decoded_content = b"original content"

        mock_repo.get_contents.return_value = mock_content
        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await get_full_file(mock_ctx, "test.py", "base")

        assert result == "original content"
        mock_repo.get_contents.assert_called_with("test.py", ref="def456")

    @pytest.mark.asyncio
    async def test_get_full_file_invalid_ref(self, mock_ctx):
        """Test file retrieval with invalid ref."""
        result = await get_full_file(mock_ctx, "test.py", "invalid")

        assert "Error" in result
        assert "Invalid ref" in result

    @pytest.mark.asyncio
    async def test_get_full_file_directory(self, mock_ctx):
        """Test file retrieval when path is a directory."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_head = Mock()
        mock_head.sha = "abc123"
        mock_pr.head = mock_head

        # Return list to simulate directory
        mock_repo.get_contents.return_value = [Mock(), Mock()]
        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await get_full_file(mock_ctx, "src/", "head")

        assert "Error" in result
        assert "directory" in result

    @pytest.mark.asyncio
    async def test_get_full_file_binary(self, mock_ctx):
        """Test file retrieval for binary file."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_head = Mock()
        mock_head.sha = "abc123"
        mock_pr.head = mock_head

        mock_content = Mock()
        mock_content.decoded_content = b"\x89PNG\r\n\x1a\n"  # Binary data

        mock_repo.get_contents.return_value = mock_content
        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await get_full_file(mock_ctx, "image.png", "head")

        assert "Error" in result
        assert "binary file" in result

    @pytest.mark.asyncio
    async def test_get_full_file_not_found(self, mock_ctx):
        """Test file retrieval when file doesn't exist."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_head = Mock()
        mock_head.sha = "abc123"
        mock_pr.head = mock_head

        mock_repo.get_contents.side_effect = GithubException(404, "Not Found", None)
        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await get_full_file(mock_ctx, "nonexistent.py", "head")

        assert "Error" in result
        assert "not found" in result


class TestPostReviewComment:
    """Tests for post_review_comment()."""

    @pytest.mark.asyncio
    async def test_post_review_comment_success(self, mock_ctx):
        """Test successful review comment posting."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_commit = Mock()

        mock_pr.get_commits.return_value = [mock_commit]
        mock_pr.create_review_comment = Mock()

        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await post_review_comment(mock_ctx, "src/test.py", 10, "Great code!")

        assert "Posted comment" in result
        assert "src/test.py:10" in result
        mock_pr.create_review_comment.assert_called_once_with(
            body="Great code!", commit=mock_commit, path="src/test.py", line=10
        )

    @pytest.mark.asyncio
    async def test_post_review_comment_github_error(self, mock_ctx):
        """Test review comment posting with GitHub error."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_commit = Mock()

        mock_pr.get_commits.return_value = [mock_commit]
        mock_pr.create_review_comment.side_effect = GithubException(
            422, "Line not in diff", None
        )

        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await post_review_comment(
            mock_ctx, "src/test.py", 999, "Comment on non-diff line"
        )

        assert "Error" in result
        assert "GitHub API error" in result


class TestPostSummaryComment:
    """Tests for post_summary_comment()."""

    @pytest.mark.asyncio
    async def test_post_summary_comment_success(self, mock_ctx):
        """Test successful summary comment posting."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_pr.create_review = Mock()

        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await post_summary_comment(mock_ctx, "Looks good!", "APPROVE")

        assert "Posted review" in result
        assert "APPROVE" in result
        mock_pr.create_review.assert_called_once_with(
            body="Looks good!", event="APPROVE"
        )

    @pytest.mark.asyncio
    async def test_post_summary_comment_default_status(self, mock_ctx):
        """Test summary comment with default status."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_pr.create_review = Mock()

        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await post_summary_comment(mock_ctx, "Review summary")

        assert "Posted review" in result
        mock_pr.create_review.assert_called_once_with(
            body="Review summary", event="COMMENT"
        )

    @pytest.mark.asyncio
    async def test_post_summary_comment_invalid_status(self, mock_ctx):
        """Test summary comment with invalid approval status."""
        result = await post_summary_comment(mock_ctx, "Summary", "INVALID_STATUS")

        assert "Error" in result
        assert "Invalid approval_status" in result

    @pytest.mark.asyncio
    async def test_post_summary_comment_request_changes(self, mock_ctx):
        """Test summary comment with REQUEST_CHANGES status."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_pr.create_review = Mock()

        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await post_summary_comment(
            mock_ctx, "Please fix these issues", "REQUEST_CHANGES"
        )

        assert "Posted review" in result
        assert "REQUEST_CHANGES" in result
        mock_pr.create_review.assert_called_once_with(
            body="Please fix these issues", event="REQUEST_CHANGES"
        )

    @pytest.mark.asyncio
    async def test_post_summary_comment_github_error(self, mock_ctx):
        """Test summary comment with GitHub error."""
        mock_repo = Mock()
        mock_pr = Mock()
        mock_pr.create_review.side_effect = GithubException(403, "Forbidden", None)

        mock_ctx.deps.github_client.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr

        result = await post_summary_comment(mock_ctx, "Summary", "COMMENT")

        assert "Error" in result
        assert "GitHub API error" in result
