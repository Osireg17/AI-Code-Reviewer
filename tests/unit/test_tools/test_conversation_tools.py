"""Unit tests for conversation tools."""

import unittest
from datetime import datetime
from unittest.mock import MagicMock

from github.ContentFile import ContentFile
from github.PullRequest import PullRequest
from github.PullRequestComment import PullRequestComment
from github.Repository import Repository
from pydantic_ai import RunContext

from src.models.dependencies import ConversationDependencies
from src.tools.conversation_tools import (
    _format_code_with_line_numbers,
    compare_code_versions,
    get_code_snippet_at_commit,
    get_comment_thread,
    get_full_file_at_commit,
)


class TestGetCodeSnippetAtCommit(unittest.TestCase):
    """Tests for get_code_snippet_at_commit function."""

    def setUp(self):
        """Set up common test fixtures."""
        self.mock_repo = MagicMock(spec=Repository)
        self.mock_deps = MagicMock(spec=ConversationDependencies)
        self.mock_deps.repo = self.mock_repo
        self.ctx = MagicMock(spec=RunContext)
        self.ctx.deps = self.mock_deps

        # Sample Python code
        self.sample_code = """def calculate_total(items):
    total = 0
    for item in items:
        total += item.price
    return total

def process_order(order):
    items = order.get_items()
    return calculate_total(items)
"""

    def test_get_code_snippet_success(self):
        """Test successfully fetching a code snippet with context."""
        # Arrange
        mock_file = MagicMock(spec=ContentFile)
        mock_file.encoding = "base64"
        mock_file.decoded_content = self.sample_code.encode("utf-8")
        self.mock_repo.get_contents.return_value = mock_file

        # Act
        result = get_code_snippet_at_commit(
            ctx=self.ctx,
            file_path="src/calculator.py",
            commit_sha="abc123def",  # pragma: allowlist secret
            line_number=4,
            context_lines=2,
        )

        # Assert
        self.assertIn(">>> ", result)  # Target line should be highlighted
        self.assertIn("total += item.price", result)  # Target line content
        self.assertIn("for item in items:", result)  # Context before
        self.assertIn("return total", result)  # Context after
        self.mock_repo.get_contents.assert_called_once_with(
            "src/calculator.py",
            ref="abc123def",  # pragma: allowlist secret
        )

    def test_get_code_snippet_binary_file(self):
        """Test handling of binary files."""
        # Arrange
        mock_file = MagicMock(spec=ContentFile)
        mock_file.encoding = "none"  # Binary files don't use base64
        self.mock_repo.get_contents.return_value = mock_file

        # Act
        result = get_code_snippet_at_commit(
            ctx=self.ctx,
            file_path="image.png",
            commit_sha="abc123",  # pragma: allowlist secret
            line_number=1,
        )

        # Assert
        self.assertEqual(result, "[Binary file - cannot display content]")

    def test_get_code_snippet_empty_file(self):
        """Test handling of empty files."""
        # Arrange
        mock_file = MagicMock(spec=ContentFile)
        mock_file.encoding = "base64"
        mock_file.decoded_content = b"   \n\n  \n"  # Only whitespace
        self.mock_repo.get_contents.return_value = mock_file

        # Act
        result = get_code_snippet_at_commit(
            ctx=self.ctx, file_path="empty.py", commit_sha="abc123", line_number=1
        )

        # Assert
        self.assertEqual(result, "[Empty file]")

    def test_get_code_snippet_line_number_out_of_bounds(self):
        """Test clamping line numbers that are out of bounds."""
        # Arrange
        mock_file = MagicMock(spec=ContentFile)
        mock_file.encoding = "base64"
        mock_file.decoded_content = self.sample_code.encode("utf-8")
        self.mock_repo.get_contents.return_value = mock_file

        # Act - line number too high
        result = get_code_snippet_at_commit(
            ctx=self.ctx,
            file_path="src/calculator.py",
            commit_sha="abc123",  # pragma: allowlist secret
            line_number=999,  # Way beyond file length
            context_lines=2,
        )

        # Assert - should clamp to last line and not crash
        self.assertIn(">>>", result)
        self.assertIsNotNone(result)

    def test_get_code_snippet_line_number_zero(self):
        """Test handling line number less than 1."""
        # Arrange
        mock_file = MagicMock(spec=ContentFile)
        mock_file.encoding = "base64"
        mock_file.decoded_content = self.sample_code.encode("utf-8")
        self.mock_repo.get_contents.return_value = mock_file

        # Act
        result = get_code_snippet_at_commit(
            ctx=self.ctx,
            file_path="src/calculator.py",
            commit_sha="abc123",  # pragma: allowlist secret
            line_number=0,
            context_lines=2,
        )

        # Assert - should clamp to line 1
        self.assertIn(">>>", result)
        self.assertIn("def calculate_total", result)

    def test_get_code_snippet_no_repo_available(self):
        """Test handling when repository is not available in context."""
        # Arrange
        self.mock_deps.repo = None

        # Act
        result = get_code_snippet_at_commit(
            ctx=self.ctx,
            file_path="src/calculator.py",
            commit_sha="abc123",  # pragma: allowlist secret
            line_number=1,
        )

        # Assert
        self.assertEqual(result, "[Error: Repository not available]")

    def test_get_code_snippet_with_context_lines(self):
        """Test that context_lines parameter controls snippet size."""
        # Arrange
        mock_file = MagicMock(spec=ContentFile)
        mock_file.encoding = "base64"
        mock_file.decoded_content = self.sample_code.encode("utf-8")
        self.mock_repo.get_contents.return_value = mock_file

        # Act - request 1 line of context
        result = get_code_snippet_at_commit(
            ctx=self.ctx,
            file_path="src/calculator.py",
            commit_sha="abc123",  # pragma: allowlist secret
            line_number=4,
            context_lines=1,
        )

        # Assert - should only have 3 lines (1 before, target, 1 after)
        lines = [line for line in result.split("\n") if line.strip()]
        self.assertLessEqual(len(lines), 3)


class TestGetFullFileAtCommit(unittest.TestCase):
    """Tests for get_full_file_at_commit function."""

    def setUp(self):
        """Set up common test fixtures."""
        self.mock_repo = MagicMock(spec=Repository)
        self.mock_deps = MagicMock(spec=ConversationDependencies)
        self.mock_deps.repo = self.mock_repo
        self.ctx = MagicMock(spec=RunContext)
        self.ctx.deps = self.mock_deps

    def test_get_full_file_success(self):
        """Test successfully fetching a full file."""
        # Arrange
        file_content = "def foo():\n    return 42\n"
        mock_file = MagicMock(spec=ContentFile)
        mock_file.encoding = "base64"
        mock_file.decoded_content = file_content.encode("utf-8")
        self.mock_repo.get_contents.return_value = mock_file

        # Act
        result = get_full_file_at_commit(
            ctx=self.ctx, file_path="src/foo.py", commit_sha="abc123"
        )

        # Assert
        self.assertEqual(result, file_content)
        self.mock_repo.get_contents.assert_called_once_with("src/foo.py", ref="abc123")

    def test_get_full_file_binary(self):
        """Test handling of binary files."""
        # Arrange
        mock_file = MagicMock(spec=ContentFile)
        mock_file.encoding = "none"
        self.mock_repo.get_contents.return_value = mock_file

        # Act
        result = get_full_file_at_commit(
            ctx=self.ctx, file_path="image.png", commit_sha="abc123"
        )

        # Assert
        self.assertEqual(result, "[Binary file - cannot display content]")

    def test_get_full_file_large_file_warning(self):
        """Test that large files trigger warning but still return content."""
        # Arrange
        large_content = "\n".join([f"line {i}" for i in range(600)])  # 600 lines
        mock_file = MagicMock(spec=ContentFile)
        mock_file.encoding = "base64"
        mock_file.decoded_content = large_content.encode("utf-8")
        self.mock_repo.get_contents.return_value = mock_file

        # Act
        result = get_full_file_at_commit(
            ctx=self.ctx, file_path="large.py", commit_sha="abc123"
        )

        # Assert - should return content despite warning
        self.assertEqual(result, large_content)
        self.assertIn("line 599", result)

    def test_get_full_file_no_repo(self):
        """Test handling when repository is not available."""
        # Arrange
        self.mock_deps.repo = None

        # Act
        result = get_full_file_at_commit(
            ctx=self.ctx, file_path="src/foo.py", commit_sha="abc123"
        )

        # Assert
        self.assertEqual(result, "[Error: Repository not available]")


class TestGetCommentThread(unittest.TestCase):
    """Tests for get_comment_thread function."""

    def setUp(self):
        """Set up common test fixtures."""
        self.mock_repo = MagicMock(spec=Repository)
        self.mock_pr = MagicMock(spec=PullRequest)
        self.mock_deps = MagicMock(spec=ConversationDependencies)
        self.ctx = MagicMock(spec=RunContext)
        self.ctx.deps = self.mock_deps

    def test_get_comment_thread_success(self):
        """Test successfully fetching a comment thread."""
        # Arrange
        root_comment_id = 100
        reply1_id = 101
        reply2_id = 102

        # Create mock comments
        root_comment = MagicMock(spec=PullRequestComment)
        root_comment.id = root_comment_id
        root_comment.user.login = "bot"
        root_comment.body = "Original bot comment"
        root_comment.created_at = datetime(2025, 1, 1, 10, 0, 0)
        root_comment.in_reply_to_id = None

        reply1 = MagicMock(spec=PullRequestComment)
        reply1.id = reply1_id
        reply1.user.login = "developer"
        reply1.body = "Why did you suggest this?"
        reply1.created_at = datetime(2025, 1, 1, 10, 5, 0)
        reply1.in_reply_to_id = root_comment_id

        reply2 = MagicMock(spec=PullRequestComment)
        reply2.id = reply2_id
        reply2.user.login = "bot"
        reply2.body = "Here's why..."
        reply2.created_at = datetime(2025, 1, 1, 10, 10, 0)
        reply2.in_reply_to_id = root_comment_id

        self.mock_pr.get_review_comments.return_value = [root_comment, reply2, reply1]
        self.mock_repo.get_pull.return_value = self.mock_pr

        # Act
        result = get_comment_thread(
            ctx=self.ctx, repo=self.mock_repo, pr_number=123, comment_id=root_comment_id
        )

        # Assert
        self.assertEqual(len(result), 3)
        # Should be sorted chronologically
        self.assertEqual(result[0]["id"], root_comment_id)
        self.assertEqual(result[1]["id"], reply1_id)
        self.assertEqual(result[2]["id"], reply2_id)
        # Check structure
        self.assertEqual(result[0]["user"], "bot")
        self.assertEqual(result[1]["body"], "Why did you suggest this?")
        self.assertIsNone(result[0]["in_reply_to_id"])
        self.assertEqual(result[1]["in_reply_to_id"], root_comment_id)

    def test_get_comment_thread_single_comment(self):
        """Test fetching thread with only root comment (no replies)."""
        # Arrange
        root_comment = MagicMock(spec=PullRequestComment)
        root_comment.id = 100
        root_comment.user.login = "bot"
        root_comment.body = "Original comment"
        root_comment.created_at = datetime(2025, 1, 1, 10, 0, 0)
        root_comment.in_reply_to_id = None

        self.mock_pr.get_review_comments.return_value = [root_comment]
        self.mock_repo.get_pull.return_value = self.mock_pr

        # Act
        result = get_comment_thread(
            ctx=self.ctx, repo=self.mock_repo, pr_number=123, comment_id=100
        )

        # Assert
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 100)

    def test_get_comment_thread_empty(self):
        """Test when comment thread is not found."""
        # Arrange
        self.mock_pr.get_review_comments.return_value = []
        self.mock_repo.get_pull.return_value = self.mock_pr

        # Act
        result = get_comment_thread(
            ctx=self.ctx, repo=self.mock_repo, pr_number=123, comment_id=999
        )

        # Assert
        self.assertEqual(len(result), 0)


class TestCompareCodeVersions(unittest.TestCase):
    """Tests for compare_code_versions function."""

    def setUp(self):
        """Set up common test fixtures."""
        self.mock_repo = MagicMock(spec=Repository)
        self.mock_deps = MagicMock(spec=ConversationDependencies)
        self.mock_deps.repo = self.mock_repo
        self.ctx = MagicMock(spec=RunContext)
        self.ctx.deps = self.mock_deps

        self.old_code = """def process_data(data):
    result = validate(data)
    return result
"""
        self.new_code = """def process_data(data):
    if not data:
        return None
    result = validate(data)
    return result
"""

    def test_compare_code_versions_with_changes(self):
        """Test comparing two different versions of code."""
        # Arrange
        old_file = MagicMock(spec=ContentFile)
        old_file.encoding = "base64"
        old_file.decoded_content = self.old_code.encode("utf-8")

        new_file = MagicMock(spec=ContentFile)
        new_file.encoding = "base64"
        new_file.decoded_content = self.new_code.encode("utf-8")

        self.mock_repo.get_contents.side_effect = [old_file, new_file]

        # Act
        result = compare_code_versions(
            ctx=self.ctx,
            file_path="src/processor.py",
            old_commit_sha="old123",
            new_commit_sha="new456",
            line_number=2,
            context_lines=2,
        )

        # Assert
        self.assertIn("=== Before", result)
        self.assertIn("=== After", result)
        self.assertIn("old123"[:7], result)
        self.assertIn("new456"[:7], result)
        self.assertNotEqual(
            result, "Code appears unchanged in this section"
        )  # Should show diff

    def test_compare_code_versions_unchanged(self):
        """Test comparing identical code versions."""
        # Arrange
        mock_file = MagicMock(spec=ContentFile)
        mock_file.encoding = "base64"
        mock_file.decoded_content = self.old_code.encode("utf-8")

        self.mock_repo.get_contents.side_effect = [mock_file, mock_file]

        # Act
        result = compare_code_versions(
            ctx=self.ctx,
            file_path="src/processor.py",
            old_commit_sha="abc123",
            new_commit_sha="abc123",
            line_number=2,
        )

        # Assert
        self.assertEqual(result, "Code appears unchanged in this section")

    def test_compare_code_versions_file_deleted(self):
        """Test comparing when file was deleted - should propagate exception."""
        # Arrange
        old_file = MagicMock(spec=ContentFile)
        old_file.encoding = "base64"
        old_file.decoded_content = self.old_code.encode("utf-8")

        # Simulate file not found in new commit
        def side_effect(path, ref):
            if ref == "old123":
                return old_file
            raise Exception("File not found")

        self.mock_repo.get_contents.side_effect = side_effect

        # Act & Assert - should propagate the exception
        with self.assertRaises(Exception) as context:
            compare_code_versions(
                ctx=self.ctx,
                file_path="src/processor.py",
                old_commit_sha="old123",
                new_commit_sha="new456",
                line_number=2,
            )

        self.assertEqual(str(context.exception), "File not found")


class TestFormatCodeWithLineNumbers(unittest.TestCase):
    """Tests for _format_code_with_line_numbers helper function."""

    def test_format_code_basic(self):
        """Test basic code formatting with line numbers."""
        # Arrange
        code_lines = ["def foo():", "    return 42", ""]

        # Act
        result = _format_code_with_line_numbers(code_lines, start_line_number=10)

        # Assert
        # Format: [4 spaces][4-digit line num][2 spaces][content]
        self.assertIn("      10  def foo():", result)
        self.assertIn("      11      return 42", result)
        self.assertIn("      12  ", result)

    def test_format_code_with_highlight(self):
        """Test highlighting a specific line."""
        # Arrange
        code_lines = ["line 1", "line 2", "line 3"]

        # Act
        result = _format_code_with_line_numbers(
            code_lines, start_line_number=5, highlight_line=6
        )

        # Assert
        # Format: [4 spaces or >>>][space][4-digit line num][2 spaces][content]
        self.assertIn(
            "       5  line 1", result
        )  # No highlight: "    " + "   5  line 1"
        self.assertIn(
            ">>>    6  line 2", result
        )  # Highlighted: ">>> " + "   6  line 2"
        self.assertIn(
            "       7  line 3", result
        )  # No highlight: "    " + "   7  line 3"

    def test_format_code_empty_list(self):
        """Test formatting empty code list."""
        # Arrange
        code_lines = []

        # Act
        result = _format_code_with_line_numbers(code_lines, start_line_number=1)

        # Assert
        self.assertEqual(result, "")

    def test_format_code_strips_trailing_whitespace(self):
        """Test that trailing whitespace is stripped from lines."""
        # Arrange
        code_lines = ["def foo():   ", "    return 42  "]

        # Act
        result = _format_code_with_line_numbers(code_lines, start_line_number=1)

        # Assert
        # Should strip trailing spaces but keep leading indentation
        self.assertIn("def foo():", result)
        self.assertNotIn("def foo():   ", result)
        self.assertIn("    return 42", result)
