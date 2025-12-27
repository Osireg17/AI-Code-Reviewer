import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from sqlalchemy.orm import Session

from src.api.handlers.conversation_handler import (
    _extract_file_context,
    _should_create_new_thread,
    handle_conversation_reply,
)
from src.models.conversation import ConversationThread


@pytest.mark.asyncio
class TestHandleConversationReply(unittest.IsolatedAsyncioTestCase):
    """Tests for the main handle_conversation_reply function."""

    async def asyncSetUp(self):
        """Set up common test fixtures."""
        self.mock_session = MagicMock(spec=Session)
        self.mock_github_auth = AsyncMock()
        self.repo_name = "owner/repo"
        self.pr_number = 123
        self.comment_id = 456
        self.in_reply_to_id = 789
        self.bot_login = "searchlightai[bot]"

        # Sample payload
        self.payload = {
            "action": "created",
            "comment": {
                "id": self.comment_id,
                "body": "Why did you suggest this?",
                "user": {"login": "developer", "id": 111, "type": "User"},
                "in_reply_to_id": self.in_reply_to_id,
                "path": "src/main.py",
                "line": 42,
                "commit_id": "abc123",
            },
            "repository": {"full_name": self.repo_name},
            "pull_request": {"number": self.pr_number},
        }

    async def test_handle_conversation_reply_success(self):
        """Test successful conversation reply flow."""
        # Arrange
        mock_session_factory = Mock(return_value=self.mock_session)
        self.mock_github_auth.get_installation_access_token = AsyncMock(
            return_value="ghs_test_token"
        )

        # Mock GitHub objects
        mock_pr = MagicMock()
        mock_pr.head.sha = "def456"
        mock_pr.create_review_comment = MagicMock()

        mock_original_comment = MagicMock()
        mock_original_comment.body = "Original bot comment"
        mock_original_comment.user.login = self.bot_login
        mock_original_comment.original_commit_id = "abc123"
        mock_pr.get_review_comment = MagicMock(return_value=mock_original_comment)

        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr

        mock_github_client = MagicMock()
        mock_github_client.get_repo.return_value = mock_repo

        # Mock conversation thread
        mock_thread = MagicMock(spec=ConversationThread)
        mock_thread.id = 1
        mock_thread.get_context_for_llm.return_value = []
        self.mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_thread
        )

        # Mock agent response
        mock_agent_result = MagicMock()
        mock_agent_result.output = "Here's why I suggested this..."

        with (
            patch("src.api.handlers.conversation_handler.Github") as mock_github,
            patch("src.api.handlers.conversation_handler.settings") as mock_settings,
            patch(
                "src.api.handlers.conversation_handler.conversation_agent"
            ) as mock_agent,
            patch(
                "src.api.handlers.conversation_handler.validate_conversation_response"
            ) as mock_validate,
            patch(
                "src.api.handlers.conversation_handler._extract_file_context"
            ) as mock_extract,
            patch("src.api.handlers.conversation_handler.ConversationDependencies"),
        ):
            mock_github.return_value = mock_github_client
            mock_settings.github_app_bot_login = self.bot_login
            mock_agent.run = AsyncMock(return_value=mock_agent_result)
            mock_validate.return_value = "Here's why I suggested this..."
            mock_extract.side_effect = ["original code", "current code"]

            # Act
            result = await handle_conversation_reply(
                payload=self.payload,
                session_factory=mock_session_factory,
                github_auth=self.mock_github_auth,
            )

            # Assert
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["message"], "Reply posted successfully")

            # Verify GitHub authentication
            self.mock_github_auth.get_installation_access_token.assert_called_once()
            mock_github_client.get_repo.assert_called_once_with(self.repo_name)
            mock_repo.get_pull.assert_called_once_with(self.pr_number)

            # Verify conversation thread was loaded
            mock_thread.get_context_for_llm.assert_called_once()

            # Verify agent was called
            mock_agent.run.assert_called_once()

            # Verify comment was posted
            # Verify comment was posted
            mock_pr.create_review_comment.assert_called_once_with(
                body="Here's why I suggested this...",
                commit="def456",
                path="src/main.py",
                in_reply_to=self.in_reply_to_id,
            )

            # Verify database updates
            self.assertEqual(mock_thread.add_message.call_count, 2)
            self.mock_session.commit.assert_called_once()
            self.mock_session.close.assert_called_once()

    async def test_handle_conversation_reply_ignores_non_created_action(self):
        """Test that non-'created' actions are skipped."""
        # Arrange
        payload = self.payload.copy()
        payload["action"] = "edited"

        # Act
        result = await handle_conversation_reply(payload=payload)

        # Assert
        self.assertEqual(result["status"], "skipped")
        self.assertIn("Ignored non-created event", result["message"])

    async def test_handle_conversation_reply_skips_non_reply_comments(self):
        """Test that comments without in_reply_to_id are skipped."""
        # Arrange
        payload = self.payload.copy()
        payload["comment"]["in_reply_to_id"] = None

        # Act
        result = await handle_conversation_reply(payload=payload)

        # Assert
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["message"], "Not a reply to bot")

    async def test_handle_conversation_reply_detects_bot_self_reply(self):
        """Test that bot self-replies are detected and skipped."""
        # Arrange
        payload = self.payload.copy()
        payload["comment"]["user"]["login"] = "searchlightai[bot]"
        payload["comment"]["user"]["type"] = "Bot"

        with patch("src.api.handlers.conversation_handler.settings") as mock_settings:
            mock_settings.github_app_bot_login = "searchlightai[bot]"

            # Act
            result = await handle_conversation_reply(payload=payload)

        # Assert
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["message"], "Bot self-reply ignored")

    async def test_handle_conversation_reply_skips_non_bot_original_comment(self):
        """Test that replies to human comments are skipped."""
        # Arrange
        mock_session_factory = Mock(return_value=self.mock_session)
        self.mock_github_auth.get_installation_access_token = AsyncMock(
            return_value="ghs_test_token"
        )

        # Mock GitHub objects
        mock_pr = MagicMock()
        mock_original_comment = MagicMock()
        mock_original_comment.user.login = "human-reviewer"  # Not the bot
        mock_pr.get_review_comment = MagicMock(return_value=mock_original_comment)

        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr

        mock_github_client = MagicMock()
        mock_github_client.get_repo.return_value = mock_repo

        # Mock conversation thread
        mock_thread = MagicMock(spec=ConversationThread)
        self.mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_thread
        )

        with (
            patch("src.api.handlers.conversation_handler.Github") as mock_github,
            patch("src.api.handlers.conversation_handler.settings") as mock_settings,
        ):
            mock_github.return_value = mock_github_client
            mock_settings.github_app_bot_login = self.bot_login

            # Act
            result = await handle_conversation_reply(
                payload=self.payload,
                session_factory=mock_session_factory,
                github_auth=self.mock_github_auth,
            )

        # Assert
        self.assertEqual(result["status"], "skipped")
        self.assertIn("Not replying to non-bot comment", result["message"])
        self.mock_session.close.assert_called_once()

    async def test_handle_conversation_reply_creates_new_thread(self):
        """Test that a new conversation thread is created if none exists."""
        # Arrange
        mock_session_factory = Mock(return_value=self.mock_session)
        self.mock_github_auth.get_installation_access_token = AsyncMock(
            return_value="ghs_test_token"
        )

        # Mock GitHub objects
        mock_pr = MagicMock()
        mock_pr.head.sha = "def456"
        mock_pr.create_review_comment = MagicMock()

        mock_original_comment = MagicMock()
        mock_original_comment.body = "Original bot comment"
        mock_original_comment.user.login = self.bot_login
        mock_original_comment.original_commit_id = "abc123"
        mock_pr.get_review_comment = MagicMock(return_value=mock_original_comment)

        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr

        mock_github_client = MagicMock()
        mock_github_client.get_repo.return_value = mock_repo

        # No existing thread
        self.mock_session.query.return_value.filter.return_value.first.return_value = (
            None
        )

        # Mock agent response
        mock_agent_result = MagicMock()
        mock_agent_result.output = "Response"

        with (
            patch("src.api.handlers.conversation_handler.Github") as mock_github,
            patch("src.api.handlers.conversation_handler.settings") as mock_settings,
            patch(
                "src.api.handlers.conversation_handler.conversation_agent"
            ) as mock_agent,
            patch(
                "src.api.handlers.conversation_handler.validate_conversation_response"
            ) as mock_validate,
            patch(
                "src.api.handlers.conversation_handler._extract_file_context"
            ) as mock_extract,
            patch(
                "src.api.handlers.conversation_handler.ConversationThread"
            ) as mock_thread_class,
            patch("src.api.handlers.conversation_handler.ConversationDependencies"),
        ):
            mock_github.return_value = mock_github_client
            mock_settings.github_app_bot_login = self.bot_login
            mock_agent.run = AsyncMock(return_value=mock_agent_result)
            mock_validate.return_value = "Response"
            mock_extract.side_effect = ["original", "current"]

            mock_new_thread = MagicMock()
            mock_new_thread.get_context_for_llm.return_value = []
            mock_thread_class.return_value = mock_new_thread

            # Act
            result = await handle_conversation_reply(
                payload=self.payload,
                session_factory=mock_session_factory,
                github_auth=self.mock_github_auth,
            )

            # Assert
            self.assertEqual(result["status"], "success")
            mock_thread_class.assert_called_once()
            self.mock_session.add.assert_called_once_with(mock_new_thread)
            self.mock_session.commit.assert_called_once()

    async def test_handle_conversation_reply_handles_code_fetch_errors(self):
        """Test graceful handling of code context fetch errors."""
        # Arrange
        mock_session_factory = Mock(return_value=self.mock_session)
        self.mock_github_auth.get_installation_access_token = AsyncMock(
            return_value="ghs_test_token"
        )

        # Mock GitHub objects
        mock_pr = MagicMock()
        mock_pr.head.sha = "def456"
        mock_pr.create_review_comment = MagicMock()

        mock_original_comment = MagicMock()
        mock_original_comment.body = "Original bot comment"
        mock_original_comment.user.login = self.bot_login
        mock_original_comment.original_commit_id = "abc123"
        mock_pr.get_review_comment = MagicMock(return_value=mock_original_comment)

        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr

        mock_github_client = MagicMock()
        mock_github_client.get_repo.return_value = mock_repo

        # Mock conversation thread
        mock_thread = MagicMock(spec=ConversationThread)
        mock_thread.get_context_for_llm.return_value = []
        self.mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_thread
        )

        # Mock agent response
        mock_agent_result = MagicMock()
        mock_agent_result.output = "Response"

        with (
            patch("src.api.handlers.conversation_handler.Github") as mock_github,
            patch("src.api.handlers.conversation_handler.settings") as mock_settings,
            patch(
                "src.api.handlers.conversation_handler.conversation_agent"
            ) as mock_agent,
            patch(
                "src.api.handlers.conversation_handler.validate_conversation_response"
            ) as mock_validate,
            patch(
                "src.api.handlers.conversation_handler._extract_file_context"
            ) as mock_extract,
            patch("src.api.handlers.conversation_handler.ConversationDependencies"),
        ):
            mock_github.return_value = mock_github_client
            mock_settings.github_app_bot_login = self.bot_login
            mock_agent.run = AsyncMock(return_value=mock_agent_result)
            mock_validate.return_value = "Response"
            # Simulate code fetch error
            mock_extract.side_effect = Exception("File not found")

            # Act
            result = await handle_conversation_reply(
                payload=self.payload,
                session_factory=mock_session_factory,
                github_auth=self.mock_github_auth,
            )

            # Assert - should still succeed with None code context
            self.assertEqual(result["status"], "success")
            mock_pr.create_review_comment.assert_called_once()
            self.mock_session.commit.assert_called_once()

    async def test_handle_conversation_reply_propagates_github_errors(self):
        """Test that GitHub API errors are propagated."""
        # Arrange
        mock_session_factory = Mock(return_value=self.mock_session)
        self.mock_github_auth.get_installation_access_token = AsyncMock(
            side_effect=Exception("GitHub API error")
        )

        # Act & Assert
        with self.assertRaises(Exception) as context:
            await handle_conversation_reply(
                payload=self.payload,
                session_factory=mock_session_factory,
                github_auth=self.mock_github_auth,
            )

        self.assertIn("GitHub API error", str(context.exception))
        # Session is never created if auth fails early, so close is not called
        self.mock_session.close.assert_not_called()

    async def test_handle_conversation_reply_closes_session_on_database_error(self):
        """Test that session is closed even when database operations fail."""
        # Arrange
        mock_session_factory = Mock(return_value=self.mock_session)
        self.mock_github_auth.get_installation_access_token = AsyncMock(
            return_value="ghs_test_token"
        )

        # Mock GitHub objects
        mock_pr = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        mock_github_client = MagicMock()
        mock_github_client.get_repo.return_value = mock_repo

        # Database query fails
        self.mock_session.query.side_effect = Exception("Database connection failed")

        with (
            patch("src.api.handlers.conversation_handler.Github") as mock_github,
            patch("src.api.handlers.conversation_handler.settings") as mock_settings,
        ):
            mock_github.return_value = mock_github_client
            mock_settings.github_app_bot_login = self.bot_login

            # Act & Assert
            with self.assertRaises(Exception) as context:
                await handle_conversation_reply(
                    payload=self.payload,
                    session_factory=mock_session_factory,
                    github_auth=self.mock_github_auth,
                )

            self.assertIn("Database connection failed", str(context.exception))
            # Session should be closed in finally block
            self.mock_session.close.assert_called_once()


@pytest.mark.asyncio
class TestExtractFileContext(unittest.IsolatedAsyncioTestCase):
    """Tests for _extract_file_context helper function."""

    def test_extract_file_context_success(self):
        """Test successful file context extraction."""
        # Arrange
        mock_repo = MagicMock()
        mock_file_content = MagicMock()
        mock_file_content.encoding = "base64"
        mock_file_content.decoded_content = (
            b"line 1\nline 2\nline 3\nline 4\nline 5\nline 6\nline 7\n"
        )
        mock_repo.get_contents.return_value = mock_file_content

        # Act
        result = _extract_file_context(
            repo=mock_repo,
            file_path="src/main.py",
            commit_sha="abc123",
            line_number=4,
            context_lines=2,
        )

        # Assert
        self.assertIn(">>> ", result)  # Target line should be highlighted
        self.assertIn("line 4", result)
        self.assertIn("line 2", result)  # Context before
        self.assertIn("line 6", result)  # Context after
        mock_repo.get_contents.assert_called_once_with("src/main.py", ref="abc123")

    def test_extract_file_context_binary_file(self):
        """Test handling of binary files."""
        # Arrange
        mock_repo = MagicMock()
        mock_file_content = MagicMock()
        mock_file_content.encoding = "none"  # Not base64
        mock_repo.get_contents.return_value = mock_file_content

        # Act
        result = _extract_file_context(
            repo=mock_repo,
            file_path="image.png",
            commit_sha="abc123",
            line_number=1,
        )

        # Assert
        self.assertEqual(result, "[Binary file - cannot display content]")

    def test_extract_file_context_empty_file(self):
        """Test handling of empty files."""
        # Arrange
        mock_repo = MagicMock()
        mock_file_content = MagicMock()
        mock_file_content.encoding = "base64"
        mock_file_content.decoded_content = b"   \n  \n"
        mock_repo.get_contents.return_value = mock_file_content

        # Act
        result = _extract_file_context(
            repo=mock_repo,
            file_path="empty.txt",
            commit_sha="abc123",
            line_number=1,
        )

        # Assert
        self.assertEqual(result, "[Empty file]")

    def test_extract_file_context_line_out_of_bounds(self):
        """Test handling of line numbers out of bounds."""
        # Arrange
        mock_repo = MagicMock()
        mock_file_content = MagicMock()
        mock_file_content.encoding = "base64"
        mock_file_content.decoded_content = b"line 1\nline 2\nline 3\n"
        mock_repo.get_contents.return_value = mock_file_content

        # Act - request line 100 (doesn't exist)
        result = _extract_file_context(
            repo=mock_repo,
            file_path="src/main.py",
            commit_sha="abc123",
            line_number=100,
            context_lines=2,
        )

        # Assert - should clamp to last line
        self.assertIn(">>> ", result)
        self.assertIn("line 3", result)


class TestShouldCreateNewThread(unittest.TestCase):
    """Tests for _should_create_new_thread helper function."""

    def test_should_create_new_thread_when_none_exists(self):
        """Test creating new thread when none exists."""
        # Arrange
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        # Act
        should_create, existing_thread = _should_create_new_thread(
            db=mock_db, in_reply_to_id=123
        )

        # Assert
        self.assertTrue(should_create)
        self.assertIsNone(existing_thread)

    def test_should_create_new_thread_when_exists(self):
        """Test using existing thread when it exists."""
        # Arrange
        mock_db = MagicMock(spec=Session)
        mock_thread = MagicMock(spec=ConversationThread)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_thread

        # Act
        should_create, existing_thread = _should_create_new_thread(
            db=mock_db, in_reply_to_id=123
        )

        # Assert
        self.assertFalse(should_create)
        self.assertEqual(existing_thread, mock_thread)
