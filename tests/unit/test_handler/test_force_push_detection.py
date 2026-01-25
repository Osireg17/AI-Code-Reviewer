"""Unit tests for force push detection in PR review handler."""

import unittest
from unittest.mock import MagicMock, patch

import pytest

from src.api.handlers.pr_review_handler import (
    _detect_force_push,
    _determine_review_type,
    _handle_force_push,
)
from src.models.review_state import ReviewState


class TestDetectForcePush:
    """Tests for _detect_force_push function."""

    def test_returns_false_when_no_base_sha(self) -> None:
        """Test returns False when base_sha is None."""
        mock_repo = MagicMock()
        mock_pr = MagicMock()

        result = _detect_force_push(mock_repo, None, mock_pr)

        assert result is False

    def test_returns_false_when_commit_exists(self) -> None:
        """Test returns False when base commit exists and is reachable."""
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.base.sha = "base123"

        # Simulate successful commit fetch and comparison
        mock_commit = MagicMock()
        mock_repo.get_commit.return_value = mock_commit

        mock_comparison = MagicMock()
        mock_comparison.status = "ahead"
        mock_comparison.ahead_by = 5
        mock_repo.compare.return_value = mock_comparison

        result = _detect_force_push(mock_repo, "abc123def456", mock_pr)

        assert result is False
        mock_repo.get_commit.assert_called_once_with(
            "abc123def456"  # pragma: allowlist secret
        )  # pragma: allowlist secret

    def test_returns_true_when_commit_not_found(self) -> None:
        """Test returns True when base commit cannot be found (force pushed)."""
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.number = 42

        # Simulate commit not found exception
        mock_repo.get_commit.side_effect = Exception("Commit not found")

        result = _detect_force_push(mock_repo, "deleted_sha123", mock_pr)

        assert result is True

    def test_returns_true_when_comparison_fails(self) -> None:
        """Test returns True when commit comparison fails."""
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.number = 42
        mock_pr.base.sha = "base123"

        # Commit exists but comparison fails
        mock_repo.get_commit.return_value = MagicMock()
        mock_repo.compare.side_effect = Exception("Comparison error")

        result = _detect_force_push(mock_repo, "problematic_sha", mock_pr)

        assert result is True


@pytest.mark.asyncio
class TestHandleForcePush(unittest.IsolatedAsyncioTestCase):
    """Tests for _handle_force_push function."""

    async def test_posts_warning_comment(self) -> None:
        """Test warning comment is posted on force push."""
        mock_pr = MagicMock()
        mock_pr.number = 42

        await _handle_force_push(
            mock_pr,
            "abc123def456789012345678901234567890abcd",  # pragma: allowlist secret
        )  # pragma: allowlist secret

        mock_pr.create_issue_comment.assert_called_once()
        call_args = mock_pr.create_issue_comment.call_args
        body = call_args.kwargs["body"]

        assert "Force Push Detected" in body
        assert "abc123d" in body  # Truncated SHA

    async def test_handles_comment_posting_error(self) -> None:
        """Test graceful handling when comment posting fails."""
        mock_pr = MagicMock()
        mock_pr.number = 42
        mock_pr.create_issue_comment.side_effect = Exception("API error")

        # Should not raise, just log warning
        await _handle_force_push(mock_pr, "abc123")

        mock_pr.create_issue_comment.assert_called_once()


@pytest.mark.asyncio
class TestDetermineReviewTypeWithForcePush(unittest.IsolatedAsyncioTestCase):
    """Tests for _determine_review_type with force push scenarios."""

    async def test_force_full_review_flag_skips_incremental(self) -> None:
        """Test force_full_review=True always returns full review."""
        mock_db = MagicMock()
        mock_pr = MagicMock()
        mock_repo = MagicMock()

        is_incremental, base_sha, state = await _determine_review_type(
            db=mock_db,
            repo_name="owner/repo",
            pr_number=123,
            pr=mock_pr,
            action="synchronize",  # Would normally be incremental
            force_full_review=True,
            repo=mock_repo,
        )

        assert is_incremental is False
        assert base_sha is None
        assert state is None

    async def test_force_push_detected_falls_back_to_full_review(self) -> None:
        """Test force push detection triggers full review fallback."""
        mock_db = MagicMock()
        mock_pr = MagicMock()
        mock_pr.head.sha = "new_sha_789"
        mock_pr.base.sha = "base_sha"
        mock_pr.number = 123
        mock_repo = MagicMock()

        # Setup existing review state
        mock_review_state = ReviewState(
            repo_full_name="owner/repo",
            pr_number=123,
            last_reviewed_commit_sha="old_sha_456",
            initial_review_completed=True,
        )
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_review_state
        mock_db.query.return_value = mock_query

        # Simulate force push (commit not found)
        mock_repo.get_commit.side_effect = Exception("Not found")

        with patch(
            "src.api.handlers.pr_review_handler._handle_force_push"
        ) as mock_handle:
            is_incremental, base_sha, state = await _determine_review_type(
                db=mock_db,
                repo_name="owner/repo",
                pr_number=123,
                pr=mock_pr,
                action="synchronize",
                force_full_review=False,
                repo=mock_repo,
            )

        # Should fall back to full review
        assert is_incremental is False
        assert base_sha is None
        # State should still be returned for cleanup purposes
        assert state == mock_review_state
        mock_handle.assert_called_once()

    async def test_no_force_push_continues_incremental(self) -> None:
        """Test normal synchronize continues with incremental review."""
        mock_db = MagicMock()
        mock_pr = MagicMock()
        mock_pr.head.sha = "new_sha_789"
        mock_pr.base.sha = "base_sha"
        mock_repo = MagicMock()

        # Setup existing review state
        mock_review_state = ReviewState(
            repo_full_name="owner/repo",
            pr_number=123,
            last_reviewed_commit_sha="old_sha_456",
            initial_review_completed=True,
        )
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_review_state
        mock_db.query.return_value = mock_query

        # Simulate successful commit fetch (no force push)
        mock_comparison = MagicMock()
        mock_comparison.status = "ahead"
        mock_comparison.ahead_by = 2
        mock_repo.compare.return_value = mock_comparison

        is_incremental, base_sha, state = await _determine_review_type(
            db=mock_db,
            repo_name="owner/repo",
            pr_number=123,
            pr=mock_pr,
            action="synchronize",
            force_full_review=False,
            repo=mock_repo,
        )

        assert is_incremental is True
        assert base_sha == "old_sha_456"
        assert state == mock_review_state
