"""Unit tests for the Code Reviewer Agent."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from github import Github, GithubException
from pydantic_ai import RunContext

from src.agents.code_reviewer import (
    add_dynamic_context,
    check_should_review_file,
    fetch_pr_context,
    get_file_diff,
    get_full_file,
    list_changed_files,
    post_review_comment,
    post_summary_comment,
    search_style_guides,
    suggest_code_fix,
    validate_review_result,
)
from src.models.dependencies import ReviewDependencies


@pytest.fixture
def review_deps():
    """Create basic ReviewDependencies for testing."""
    mock_github = MagicMock(spec=Github)
    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    return ReviewDependencies(
        github_client=mock_github,
        http_client=mock_http_client,
        pr_number=123,
        repo_full_name="owner/repo",
        db_session=None,
        is_incremental_review=False,
        base_commit_sha=None,
        repo=None,
        pr=None,
    )


@pytest.fixture
def mock_run_context(review_deps):
    """Create mock RunContext with ReviewDependencies."""
    context = MagicMock(spec=RunContext)
    context.deps = review_deps
    return context


# === TOOL TESTS ===
class TestFetchPRContext:
    """Tests for fetch_pr_context tool."""

    @pytest.mark.asyncio
    async def test_fetch_pr_context_success(self, mock_run_context):
        """Test successful fetching of PR context."""
        expected_result = {"number": 123, "title": "Test PR", "author": "testuser"}

        with patch(
            "src.tools.github_tools.fetch_pr_context", return_value=expected_result
        ) as mock_fetch:
            result = await fetch_pr_context(mock_run_context)

            assert result == expected_result
            mock_fetch.assert_called_once_with(mock_run_context)

    @pytest.mark.asyncio
    async def test_fetch_pr_context_failure(self, mock_run_context):
        with patch("src.tools.github_tools.fetch_pr_context") as mock_fetch:
            mock_fetch.side_effect = GithubException(
                status=404, data={"message": "Not Found"}, headers={}
            )

            # Verify exception is raised
            with pytest.raises(GithubException) as exc_info:
                await fetch_pr_context(mock_run_context)

            assert exc_info.value.status == 404
            mock_fetch.assert_called_once_with(mock_run_context)


class TestListChangedFiles:
    """Tests for list_changed_files tool."""

    @pytest.mark.asyncio
    async def test_list_changed_files_success(self, mock_run_context):
        """Test successful listing of changed files."""
        expected_files = ["file1.py", "file2.js"]

        with patch(
            "src.tools.github_tools.list_changed_files", return_value=expected_files
        ) as mock_list:
            result = await list_changed_files(mock_run_context)

            assert result == expected_files
            mock_list.assert_called_once_with(mock_run_context)

    @pytest.mark.asyncio
    async def test_list_changed_files_failure(self, mock_run_context):
        with patch("src.tools.github_tools.list_changed_files") as mock_list:
            mock_list.side_effect = GithubException(
                status=500, data={"message": "Internal Server Error"}, headers={}
            )

            # Verify exception is raised
            with pytest.raises(GithubException) as exc_info:
                await list_changed_files(mock_run_context)

            assert exc_info.value.status == 500
            mock_list.assert_called_once_with(mock_run_context)


class TestCheckShouldReviewFile:
    """Tests for check_should_review_file tool."""

    @pytest.mark.asyncio
    async def test_check_should_review_file_true(self, mock_run_context):
        """Test file should be reviewed."""
        file_path = "src/main.py"

        with patch(
            "src.tools.github_tools.check_should_review_file", return_value=True
        ) as mock_check:
            result = await check_should_review_file(mock_run_context, file_path)

            assert result is True
            mock_check.assert_called_once_with(mock_run_context, file_path)

    @pytest.mark.asyncio
    async def test_check_should_review_file_false(self, mock_run_context):
        """Test file should not be reviewed."""
        file_path = "docs/readme.md"

        with patch(
            "src.tools.github_tools.check_should_review_file", return_value=False
        ) as mock_check:
            result = await check_should_review_file(mock_run_context, file_path)

            assert result is False
            mock_check.assert_called_once_with(mock_run_context, file_path)


class TestGetFileDiff:
    """Tests for get_file_diff tool."""

    @pytest.mark.asyncio
    async def test_get_file_diff_success(self, mock_run_context):
        """Test successful fetching of file diff."""
        file_path = "src/main.py"
        expected_diff = "--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-print('Hello')\n+print('Hello, World!')"

        with patch(
            "src.tools.github_tools.get_file_diff", return_value=expected_diff
        ) as mock_get_diff:
            result = await get_file_diff(mock_run_context, file_path)

            assert result == expected_diff
            mock_get_diff.assert_called_once_with(mock_run_context, file_path)

    @pytest.mark.asyncio
    async def test_get_file_diff_failure(self, mock_run_context):
        """Test failure in fetching file diff."""
        file_path = "src/main.py"

        with patch("src.tools.github_tools.get_file_diff") as mock_get_diff:
            mock_get_diff.side_effect = GithubException(
                status=404, data={"message": "Not Found"}, headers={}
            )

            # Verify exception is raised
            with pytest.raises(GithubException) as exc_info:
                await get_file_diff(mock_run_context, file_path)

            assert exc_info.value.status == 404
            mock_get_diff.assert_called_once_with(mock_run_context, file_path)


class TestGetFullFile:
    """Tests for get_full_file tool."""

    @pytest.mark.asyncio
    async def test_get_full_file_success(self, mock_run_context):
        """Test successful fetching of full file content."""
        file_path = "src/main.py"
        expected_content = "print('Hello, World!')\n"

        with patch(
            "src.tools.github_tools.get_full_file", return_value=expected_content
        ) as mock_get_file:
            result = await get_full_file(mock_run_context, file_path)

            assert result == expected_content
            mock_get_file.assert_called_once_with(mock_run_context, file_path, "head")

    @pytest.mark.asyncio
    async def test_get_full_file_failure(self, mock_run_context):
        """Test failure in fetching full file content."""
        file_path = "src/main.py"

        with patch("src.tools.github_tools.get_full_file") as mock_get_file:
            mock_get_file.side_effect = GithubException(
                status=404, data={"message": "Not Found"}, headers={}
            )

            # Verify exception is raised
            with pytest.raises(GithubException) as exc_info:
                await get_full_file(mock_run_context, file_path)

            assert exc_info.value.status == 404
            mock_get_file.assert_called_once_with(mock_run_context, file_path, "head")


class TestPostReviewComment:
    """Tests for post_review_comment tool."""

    @pytest.mark.asyncio
    async def test_post_review_comment_success(self, mock_run_context):
        """Test successful posting of review comment."""
        file_path = "src/main.py"
        line_number = 10
        comment_body = "Please improve this function."

        with patch("src.tools.github_tools.post_review_comment") as mock_post_comment:
            await post_review_comment(
                mock_run_context, file_path, line_number, comment_body
            )

            mock_post_comment.assert_called_once_with(
                mock_run_context, file_path, line_number, comment_body
            )

    @pytest.mark.asyncio
    async def test_post_review_comment_failure(self, mock_run_context):
        """Test failure in posting review comment."""
        file_path = "src/main.py"
        line_number = 10
        comment_body = "Please improve this function."

        with patch("src.tools.github_tools.post_review_comment") as mock_post_comment:
            mock_post_comment.side_effect = GithubException(
                status=403, data={"message": "Forbidden"}, headers={}
            )

            # Verify exception is raised
            with pytest.raises(GithubException) as exc_info:
                await post_review_comment(
                    mock_run_context, file_path, line_number, comment_body
                )

            assert exc_info.value.status == 403
            mock_post_comment.assert_called_once_with(
                mock_run_context, file_path, line_number, comment_body
            )


class TestPostSummaryComment:
    """Tests for post_summary_comment tool."""

    @pytest.mark.asyncio
    async def test_post_summary_comment_success(self, mock_run_context):
        """Test successful posting of summary comment."""
        summary_body = "Overall, the code looks good."

        with patch("src.tools.github_tools.post_summary_comment") as mock_post_summary:
            await post_summary_comment(mock_run_context, summary_body)

            mock_post_summary.assert_called_once_with(
                mock_run_context, summary_body, "COMMENT"
            )

    @pytest.mark.asyncio
    async def test_post_summary_comment_failure(self, mock_run_context):
        """Test failure in posting summary comment."""
        summary_body = "Overall, the code looks good."

        with patch("src.tools.github_tools.post_summary_comment") as mock_post_summary:
            mock_post_summary.side_effect = GithubException(
                status=403, data={"message": "Forbidden"}, headers={}
            )

            # Verify exception is raised
            with pytest.raises(GithubException) as exc_info:
                await post_summary_comment(mock_run_context, summary_body)

            assert exc_info.value.status == 403
            mock_post_summary.assert_called_once_with(
                mock_run_context, summary_body, "COMMENT"
            )


class TestSearchStyleGuides:
    """Tests for search_style_guides tool."""

    @pytest.mark.asyncio
    async def test_search_style_guides_success(self, mock_run_context):
        """Test successful search of style guides."""
        query = "naming conventions"
        language = "python"
        expected_results = "Found style guide: PEP 8"

        with patch(
            "src.tools.rag_tools.search_style_guides", return_value=expected_results
        ) as mock_search:
            result = await search_style_guides(mock_run_context, query, language)

            assert result == expected_results
            mock_search.assert_called_once_with(mock_run_context, query, language, 3)

    @pytest.mark.asyncio
    async def test_search_style_guides_failure(self, mock_run_context):
        """Test failure in searching style guides."""
        query = "naming conventions"
        language = "python"

        with patch("src.tools.rag_tools.search_style_guides") as mock_search:
            mock_search.side_effect = Exception("Search error")

            # Verify exception is raised
            with pytest.raises(Exception) as exc_info:
                await search_style_guides(mock_run_context, query, language)

            assert str(exc_info.value) == "Search error"
            mock_search.assert_called_once_with(mock_run_context, query, language, 3)


class TestSuggestCodeFix:
    """Tests for suggest_code_fix tool."""

    @pytest.mark.asyncio
    async def test_suggest_code_fix_success(self, mock_run_context):
        """Test successful code fix suggestion."""
        explanation = "Variable name violates PEP 8 snake_case convention"
        new_code = "user_data = get_user_info()"
        issue_category = "naming"
        file_path = "src/main.py"
        expected_suggestion = "Refactor function into smaller functions."

        with patch(
            "src.tools.conversation_tools.suggest_code_fix",
            return_value=expected_suggestion,
        ) as mock_suggest:
            result = await suggest_code_fix(
                mock_run_context, explanation, new_code, issue_category, file_path
            )

            assert result == expected_suggestion
            mock_suggest.assert_called_once_with(
                ctx=mock_run_context,
                explanation=explanation,
                new_code=new_code,
                issue_category=issue_category,
                file_path=file_path,
            )

    @pytest.mark.asyncio
    async def test_suggest_code_fix_failure(self, mock_run_context):
        """Test failure in code fix suggestion."""
        explanation = "Variable name violates PEP 8 snake_case convention"
        new_code = "user_data = get_user_info()"
        issue_category = "naming"
        file_path = "src/main.py"

        with patch("src.tools.conversation_tools.suggest_code_fix") as mock_suggest:
            mock_suggest.side_effect = Exception("AI error")

            # Verify exception is raised
            with pytest.raises(Exception) as exc_info:
                await suggest_code_fix(
                    mock_run_context, explanation, new_code, issue_category, file_path
                )

            assert str(exc_info.value) == "AI error"
            mock_suggest.assert_called_once_with(
                ctx=mock_run_context,
                explanation=explanation,
                new_code=new_code,
                issue_category=issue_category,
                file_path=file_path,
            )


class TestAddDynamicContext:
    """Tests for add_dynamic_context tool."""

    @pytest.mark.asyncio
    async def test_add_dynamic_context_success(self, mock_run_context):
        """Test successful addition of dynamic context."""
        expected_context = "\nRepo: owner/repo | PR: #123 | Max files: 10\n\nIf >10 files: prioritize security/auth, core logic, APIs. Skip generated/lock files.\n"

        result = await add_dynamic_context(mock_run_context)

        assert result == expected_context

    @pytest.mark.asyncio
    async def test_add_dynamic_context_with_missing_deps(self, mock_run_context):
        """Test add_dynamic_context with missing dependencies."""
        # Set deps to None to simulate missing dependencies
        mock_run_context.deps = None

        with pytest.raises(AttributeError):
            await add_dynamic_context(mock_run_context)


class TestValidateReviewResult:
    """Tests for validate_review_result tool."""

    @pytest.mark.asyncio
    async def test_validate_review_result_success(self, mock_run_context):
        """Test successful validation of review result."""
        from src.models.outputs import CodeReviewResult, ReviewSummary

        # Create a mock CodeReviewResult
        mock_result = CodeReviewResult(
            comments=[],
            summary=ReviewSummary(
                critical_issues=0,
                warnings=0,
                suggestions=0,
                praise_count=0,
                files_reviewed=1,
                recommendation="APPROVE",
                overall_assessment="The code looks good.",
            ),
            total_comments=0,
        )

        result = validate_review_result(
            repo_full_name="owner/repo", pr_number=123, result=mock_result
        )

        assert result == mock_result
        assert result.summary.critical_issues == 0
        assert result.summary.recommendation == "APPROVE"
