import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from github.PullRequest import PullRequest
from sqlalchemy.orm import Session

from src.api.handlers.pr_review_handler import (
    _determine_review_type,
    _post_inline_comments_if_needed,
    _post_progress_comment_if_needed,
    _post_summary_review_if_needed,
    _run_code_review_agent,
    _update_review_state,
    handle_pr_review,
)
from src.models.outputs import CodeReviewResult, ReviewComment, ReviewSummary
from src.models.review_state import ReviewState


@pytest.mark.asyncio
class TestHandlePRReview(unittest.IsolatedAsyncioTestCase):
    """Tests for the main handle_pr_review function."""

    async def asyncSetUp(self):
        """Set up common test fixtures."""
        self.mock_session = MagicMock(spec=Session)
        self.mock_github_auth = AsyncMock()
        self.mock_agent = AsyncMock()
        self.repo_name = "owner/repo"
        self.pr_number = 123

    async def test_handle_pr_review_success(self):
        """Test successful PR review flow."""
        # Arrange
        mock_session_factory = Mock(return_value=self.mock_session)
        mock_pr = MagicMock(spec=PullRequest)
        mock_pr.state = "open"
        mock_pr.number = self.pr_number
        mock_pr.head.sha = "abc123def456"  # pragma: allowlist secret

        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr

        mock_github_client = MagicMock()
        mock_github_client.get_repo.return_value = mock_repo

        self.mock_github_auth.get_installation_access_token = AsyncMock(
            return_value="ghs_test_token"
        )

        # Mock ReviewDependencies to avoid Pydantic validation issues
        mock_deps = MagicMock()

        # Mock the helper functions to avoid deep integration
        with (
            patch(
                "src.api.handlers.pr_review_handler.Github",
                return_value=mock_github_client,
            ),
            patch(
                "src.api.handlers.pr_review_handler.ReviewDependencies",
                return_value=mock_deps,
            ),
            patch(
                "src.api.handlers.pr_review_handler._determine_review_type"
            ) as mock_determine,
            patch(
                "src.api.handlers.pr_review_handler._post_progress_comment_if_needed"
            ) as mock_progress,
            patch(
                "src.api.handlers.pr_review_handler._run_code_review_agent"
            ) as mock_run_agent,
            patch(
                "src.api.handlers.pr_review_handler._post_inline_comments_if_needed"
            ) as mock_inline,
            patch(
                "src.api.handlers.pr_review_handler._post_summary_review_if_needed"
            ) as mock_summary,
            patch(
                "src.api.handlers.pr_review_handler._update_review_state"
            ) as mock_update,
        ):
            # Setup mock return values
            mock_determine.return_value = (False, None, None)  # Full review
            mock_validated_result = CodeReviewResult(
                summary=ReviewSummary(
                    overall_assessment="Good",
                    files_reviewed=1,
                    recommendation="APPROVE",
                ),
                comments=[],
            )
            mock_run_agent.return_value = mock_validated_result

            # Act
            await handle_pr_review(
                repo_name=self.repo_name,
                pr_number=self.pr_number,
                action="opened",
                session_factory=mock_session_factory,
                github_auth=self.mock_github_auth,
                agent=self.mock_agent,
            )

            # Assert
            self.mock_github_auth.get_installation_access_token.assert_called_once()
            mock_github_client.get_repo.assert_called_once_with(self.repo_name)
            mock_repo.get_pull.assert_called_once_with(self.pr_number)

            # Verify all helper functions were called
            mock_determine.assert_called_once()
            mock_progress.assert_called_once_with(mock_pr, "opened")
            mock_run_agent.assert_called_once()
            mock_inline.assert_called_once()
            mock_summary.assert_called_once()
            mock_update.assert_called_once()

            # Verify session was closed
            self.mock_session.close.assert_called_once()

    @patch("src.api.handlers.pr_review_handler.Github")
    @patch("src.api.handlers.pr_review_handler.Auth")
    async def test_handle_pr_review_skips_closed_pr(self, mock_auth, mock_github):
        """Test that closed PRs are skipped."""
        # Setup
        mock_session_factory = Mock(return_value=self.mock_session)
        self.mock_github_auth.get_installation_access_token = AsyncMock(
            return_value="token123"
        )

        # Mock closed PR
        mock_pr = MagicMock()
        mock_pr.state = "closed"

        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr

        mock_github_client = MagicMock()
        mock_github_client.get_repo.return_value = mock_repo
        mock_github.return_value = mock_github_client

        # Execute
        await handle_pr_review(
            repo_name=self.repo_name,
            pr_number=self.pr_number,
            action="opened",
            session_factory=mock_session_factory,
            github_auth=self.mock_github_auth,
            agent=self.mock_agent,
        )

        # Verify - should return early without processing
        self.mock_session.close.assert_called_once()
        self.mock_agent.run.assert_not_called()

    @patch("src.api.handlers.pr_review_handler.Github")
    @patch("src.api.handlers.pr_review_handler.Auth")
    async def test_handle_pr_review_handles_exceptions(self, mock_auth, mock_github):
        """Test error handling in main flow."""
        # Setup
        mock_session_factory = Mock(return_value=self.mock_session)
        self.mock_github_auth.get_installation_access_token = AsyncMock(
            side_effect=Exception("Auth failed")
        )

        # Execute and verify exception is propagated
        with self.assertRaises(Exception) as context:
            await handle_pr_review(
                repo_name=self.repo_name,
                pr_number=self.pr_number,
                action="opened",
                session_factory=mock_session_factory,
                github_auth=self.mock_github_auth,
                agent=self.mock_agent,
            )

        self.assertIn("Auth failed", str(context.exception))
        # Session should still be closed in finally block
        self.mock_session.close.assert_called_once()


@pytest.mark.asyncio
class TestDetermineReviewType(unittest.IsolatedAsyncioTestCase):
    """Tests for _determine_review_type helper."""

    async def test_determine_review_type_opened_action(self):
        """Test full review for 'opened' action."""
        # Setup
        mock_db = MagicMock(spec=Session)
        mock_pr = MagicMock()
        repo_name = "owner/repo"
        pr_number = 123

        # Execute
        is_incremental, base_commit, review_state = await _determine_review_type(
            db=mock_db,
            repo_name=repo_name,
            pr_number=pr_number,
            pr=mock_pr,
            action="opened",
        )

        # Assert
        self.assertFalse(is_incremental)
        self.assertIsNone(base_commit)
        self.assertIsNone(review_state)

    async def test_determine_review_type_synchronize_with_existing_state(self):
        """Test incremental review with existing state."""
        # Setup
        mock_db = MagicMock(spec=Session)
        mock_pr = MagicMock()
        mock_pr.head.sha = "new_sha_123"

        # Create mock review state
        mock_review_state = ReviewState(
            repo_full_name="owner/repo",
            pr_number=123,
            last_reviewed_commit_sha="old_sha_456",
            initial_review_completed=True,
        )

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_review_state
        mock_db.query.return_value = mock_query

        # Execute
        is_incremental, base_commit, review_state = await _determine_review_type(
            db=mock_db,
            repo_name="owner/repo",
            pr_number=123,
            pr=mock_pr,
            action="synchronize",
        )

        # Assert
        self.assertTrue(is_incremental)
        self.assertEqual(base_commit, "old_sha_456")
        self.assertEqual(review_state, mock_review_state)

    async def test_determine_review_type_synchronize_without_existing_state(self):
        """Test falls back to full review when no prior state."""
        # Setup
        mock_db = MagicMock(spec=Session)
        mock_pr = MagicMock()

        # No existing state
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query

        # Execute
        is_incremental, base_commit, review_state = await _determine_review_type(
            db=mock_db,
            repo_name="owner/repo",
            pr_number=123,
            pr=mock_pr,
            action="synchronize",
        )

        # Assert - should fall back to full review
        self.assertFalse(is_incremental)
        self.assertIsNone(base_commit)
        self.assertIsNone(review_state)


@pytest.mark.asyncio
class TestPostProgressComment(unittest.IsolatedAsyncioTestCase):
    """Tests for _post_progress_comment_if_needed helper."""

    @patch("src.api.handlers.pr_review_handler.settings")
    async def test_posts_comment_for_opened_action(self, mock_settings):
        """Test progress comment is posted for 'opened' event."""
        # Setup
        mock_settings.bot_name = "TestBot"
        mock_pr = MagicMock()

        # Execute
        await _post_progress_comment_if_needed(pr=mock_pr, action="opened")

        # Assert
        mock_pr.create_issue_comment.assert_called_once()
        call_args = mock_pr.create_issue_comment.call_args
        self.assertIn("TestBot", call_args.kwargs["body"])

    @patch("src.api.handlers.pr_review_handler.settings")
    async def test_posts_comment_for_reopened_action(self, mock_settings):
        """Test progress comment is posted for 'reopened' event."""
        # Setup
        mock_settings.bot_name = "TestBot"
        mock_pr = MagicMock()

        # Execute
        await _post_progress_comment_if_needed(pr=mock_pr, action="reopened")

        # Assert
        mock_pr.create_issue_comment.assert_called_once()

    async def test_skips_comment_for_synchronize_action(self):
        """Test no comment for 'synchronize' event."""
        # Setup
        mock_pr = MagicMock()

        # Execute
        await _post_progress_comment_if_needed(pr=mock_pr, action="synchronize")

        # Assert
        mock_pr.create_issue_comment.assert_not_called()


@pytest.mark.asyncio
class TestRunCodeReviewAgent(unittest.IsolatedAsyncioTestCase):
    """Tests for _run_code_review_agent helper."""

    @patch("src.api.handlers.pr_review_handler.with_exponential_backoff")
    @patch("src.api.handlers.pr_review_handler.validate_review_result")
    async def test_runs_agent_successfully(
        self, mock_validate_result, mock_with_backoff
    ):
        """Test agent runs and returns validated result."""
        # Setup
        mock_agent = AsyncMock()
        mock_deps = MagicMock()

        mock_agent_result = MagicMock()
        mock_agent_result.output = CodeReviewResult(
            summary=ReviewSummary(
                overall_assessment="Good", files_reviewed=1, recommendation="APPROVE"
            ),
            comments=[],
        )

        mock_with_backoff.return_value = mock_agent_result

        validated_result = CodeReviewResult(
            summary=ReviewSummary(
                overall_assessment="Good", files_reviewed=1, recommendation="APPROVE"
            ),
            comments=[],
        )
        mock_validate_result.return_value = validated_result

        # Execute
        result = await _run_code_review_agent(
            repo_name="owner/repo", pr_number=123, deps=mock_deps, agent=mock_agent
        )

        # Assert
        mock_with_backoff.assert_called_once()
        mock_validate_result.assert_called_once_with(
            repo_full_name="owner/repo",
            pr_number=123,
            result=mock_agent_result.output,
        )
        self.assertEqual(result, validated_result)

    @patch("src.api.handlers.pr_review_handler.with_exponential_backoff")
    async def test_handles_agent_failure_with_retry(self, mock_with_backoff):
        """Test exponential backoff retry logic."""
        # Setup
        mock_agent = AsyncMock()
        mock_deps = MagicMock()

        # Simulate retry failure
        mock_with_backoff.side_effect = Exception("Agent failed after retries")

        # Execute and verify
        with self.assertRaises(Exception) as context:
            await _run_code_review_agent(
                repo_name="owner/repo", pr_number=123, deps=mock_deps, agent=mock_agent
            )

        self.assertIn("Agent failed", str(context.exception))
        mock_with_backoff.assert_called_once()


@pytest.mark.asyncio
class TestPostInlineComments(unittest.IsolatedAsyncioTestCase):
    """Tests for _post_inline_comments_if_needed helper."""

    @patch("src.tools.github_tools._is_line_in_diff")
    async def test_posts_valid_comments(self, mock_is_line_in_diff):
        """Test posting comments on valid diff lines."""
        # Setup
        mock_pr = MagicMock()
        mock_file = MagicMock()
        mock_file.filename = "test.py"
        mock_file.patch = "@@ -1,3 +1,4 @@\n line content"
        mock_pr.get_files.return_value = [mock_file]
        mock_pr.head.sha = "abc123"

        mock_deps = MagicMock()
        mock_deps._cache = {}

        comment = ReviewComment(
            file_path="test.py",
            line_number=10,
            comment_body="Test comment",
            severity="warning",
            category="code_quality",
        )

        validated_result = CodeReviewResult(
            summary=ReviewSummary(
                overall_assessment="Good", files_reviewed=1, recommendation="APPROVE"
            ),
            comments=[comment],
        )

        mock_is_line_in_diff.return_value = True

        # Execute
        await _post_inline_comments_if_needed(
            pr=mock_pr, validated_result=validated_result, deps=mock_deps
        )

        # Assert
        mock_pr.create_review_comment.assert_called_once_with(
            body="Test comment", commit="abc123", path="test.py", line=10
        )

    @patch("src.tools.github_tools._is_line_in_diff")
    async def test_skips_comments_not_in_diff(self, mock_is_line_in_diff):
        """Test skipping comments on unchanged lines."""
        # Setup
        mock_pr = MagicMock()
        mock_file = MagicMock()
        mock_file.filename = "test.py"
        mock_file.patch = "@@ -1,3 +1,4 @@\n line content"
        mock_pr.get_files.return_value = [mock_file]

        mock_deps = MagicMock()
        mock_deps._cache = {}

        comment = ReviewComment(
            file_path="test.py",
            line_number=10,
            comment_body="Test comment",
            severity="warning",
            category="code_quality",
        )

        validated_result = CodeReviewResult(
            summary=ReviewSummary(
                overall_assessment="Good", files_reviewed=1, recommendation="APPROVE"
            ),
            comments=[comment],
        )

        mock_is_line_in_diff.return_value = False

        # Execute
        await _post_inline_comments_if_needed(
            pr=mock_pr, validated_result=validated_result, deps=mock_deps
        )

        # Assert - comment should be skipped
        mock_pr.create_review_comment.assert_not_called()

    async def test_skips_when_already_posted_by_agent(self):
        """Test cache flag prevents duplicate posting."""
        # Setup
        mock_pr = MagicMock()
        mock_deps = MagicMock()
        mock_deps._cache = {"inline_comments_posted": True}

        validated_result = CodeReviewResult(
            summary=ReviewSummary(
                overall_assessment="Good", files_reviewed=1, recommendation="APPROVE"
            ),
            comments=[],
        )

        # Execute
        await _post_inline_comments_if_needed(
            pr=mock_pr, validated_result=validated_result, deps=mock_deps
        )

        # Assert
        mock_pr.get_files.assert_not_called()
        mock_pr.create_review_comment.assert_not_called()


@pytest.mark.asyncio
class TestPostSummaryReview(unittest.IsolatedAsyncioTestCase):
    """Tests for _post_summary_review_if_needed helper."""

    async def test_posts_summary_for_full_review(self):
        """Test summary is posted for non-incremental reviews."""
        # Setup
        mock_pr = MagicMock()
        mock_deps = MagicMock()
        mock_deps._cache = {}

        # Note: recommendation must be uppercase to match the mapping in pr_review_handler.py:219-223
        validated_result = CodeReviewResult(
            summary=ReviewSummary(
                overall_assessment="Good work!",
                files_reviewed=1,
                recommendation="APPROVE",
            ),
            comments=[],
        )

        # Execute
        await _post_summary_review_if_needed(
            pr=mock_pr,
            validated_result=validated_result,
            deps=mock_deps,
            is_incremental=False,
        )

        # Assert
        mock_pr.create_review.assert_called_once()
        call_kwargs = mock_pr.create_review.call_args.kwargs
        self.assertIn("Good work!", call_kwargs["body"])
        self.assertEqual(call_kwargs["event"], "APPROVE")

    async def test_posts_incremental_summary_for_synchronize(self):
        """Test incremental summary is posted for synchronize events."""
        # Setup
        mock_pr = MagicMock()
        mock_pr.head.sha = "new_sha_789"
        mock_deps = MagicMock()
        mock_deps._cache = {}

        validated_result = CodeReviewResult(
            summary=ReviewSummary(
                overall_assessment="Good", files_reviewed=1, recommendation="APPROVE"
            ),
            comments=[],
        )

        # Execute
        await _post_summary_review_if_needed(
            pr=mock_pr,
            validated_result=validated_result,
            deps=mock_deps,
            is_incremental=True,
            base_commit_sha="old_sha_456",
        )

        # Assert - should post issue comment (incremental summary) instead of review
        mock_pr.create_review.assert_not_called()
        mock_pr.create_issue_comment.assert_called_once()
        call_args = mock_pr.create_issue_comment.call_args
        body = call_args.kwargs["body"]
        self.assertIn("Incremental Review Update", body)
        self.assertIn("old_sha", body)  # base commit
        self.assertIn("new_sha", body)  # head commit

    async def test_uses_approve_status(self):
        """Test APPROVE status mapping."""
        # Setup
        mock_pr = MagicMock()
        mock_deps = MagicMock()
        mock_deps._cache = {}

        validated_result = CodeReviewResult(
            summary=ReviewSummary(
                overall_assessment="Test",
                files_reviewed=1,
                recommendation="APPROVE",
            ),
            comments=[],
        )

        # Execute
        await _post_summary_review_if_needed(
            pr=mock_pr,
            validated_result=validated_result,
            deps=mock_deps,
            is_incremental=False,
        )

        # Assert
        call_kwargs = mock_pr.create_review.call_args.kwargs
        self.assertEqual(call_kwargs["event"], "APPROVE")

    async def test_uses_request_changes_status(self):
        """Test REQUEST_CHANGES status mapping."""
        # Setup
        mock_pr = MagicMock()
        mock_deps = MagicMock()
        mock_deps._cache = {}

        validated_result = CodeReviewResult(
            summary=ReviewSummary(
                overall_assessment="Test",
                files_reviewed=1,
                recommendation="REQUEST_CHANGES",
            ),
            comments=[],
        )

        # Execute
        await _post_summary_review_if_needed(
            pr=mock_pr,
            validated_result=validated_result,
            deps=mock_deps,
            is_incremental=False,
        )

        # Assert
        call_kwargs = mock_pr.create_review.call_args.kwargs
        self.assertEqual(call_kwargs["event"], "REQUEST_CHANGES")

    async def test_uses_comment_status(self):
        """Test COMMENT status mapping."""
        # Setup
        mock_pr = MagicMock()
        mock_deps = MagicMock()
        mock_deps._cache = {}

        validated_result = CodeReviewResult(
            summary=ReviewSummary(
                overall_assessment="Test",
                files_reviewed=1,
                recommendation="COMMENT",
            ),
            comments=[],
        )

        # Execute
        await _post_summary_review_if_needed(
            pr=mock_pr,
            validated_result=validated_result,
            deps=mock_deps,
            is_incremental=False,
        )

        # Assert
        call_kwargs = mock_pr.create_review.call_args.kwargs
        self.assertEqual(call_kwargs["event"], "COMMENT")


@pytest.mark.asyncio
class TestUpdateReviewState(unittest.IsolatedAsyncioTestCase):
    """Tests for _update_review_state helper."""

    async def test_updates_existing_review_state(self):
        """Test updating existing ReviewState record."""
        # Setup
        mock_db = MagicMock(spec=Session)
        mock_pr = MagicMock()
        mock_pr.head.sha = "new_sha_789"

        existing_state = ReviewState(
            repo_full_name="owner/repo",
            pr_number=123,
            last_reviewed_commit_sha="old_sha_456",
            initial_review_completed=True,
        )

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = existing_state
        mock_db.query.return_value = mock_query

        # Execute
        await _update_review_state(
            db=mock_db,
            repo_name="owner/repo",
            pr_number=123,
            pr=mock_pr,
            is_incremental=True,
            review_key="owner/repo#123",
        )

        # Assert
        self.assertEqual(existing_state.last_reviewed_commit_sha, "new_sha_789")
        mock_db.commit.assert_called_once()

    async def test_creates_new_review_state(self):
        """Test creating new ReviewState when none exists."""
        # Setup
        mock_db = MagicMock(spec=Session)
        mock_pr = MagicMock()
        mock_pr.head.sha = "new_sha_789"

        # No existing state
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query

        # Execute
        await _update_review_state(
            db=mock_db,
            repo_name="owner/repo",
            pr_number=123,
            pr=mock_pr,
            is_incremental=False,
            review_key="owner/repo#123",
        )

        # Assert
        mock_db.add.assert_called_once()
        added_state = mock_db.add.call_args[0][0]
        self.assertIsInstance(added_state, ReviewState)
        self.assertEqual(added_state.repo_full_name, "owner/repo")
        self.assertEqual(added_state.pr_number, 123)
        self.assertEqual(added_state.last_reviewed_commit_sha, "new_sha_789")
        self.assertTrue(added_state.initial_review_completed)
        mock_db.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
