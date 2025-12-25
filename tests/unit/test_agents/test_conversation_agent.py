"""Unit tests for conversation agent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext

from src.agents.conversation_agent import (
    check_code_changes,
    get_code_context,
    search_coding_standards,
    validate_conversation_response,
)
from src.models.dependencies import ConversationDependencies

# === FIXTURES ===


@pytest.fixture
def conversation_deps():
    """Create basic ConversationDependencies for testing."""
    return ConversationDependencies(
        conversation_history=[
            {"role": "assistant", "content": "I suggest using type hints."},
            {"role": "user", "content": "Why is this important?"},
        ],
        user_question="Can you explain more about type hints?",
        original_bot_comment="Consider adding type hints to this function for better code clarity.",
        file_path="src/utils/helpers.py",
        line_number=42,
        original_code_snippet="def process_data(data):\n    return data.strip()",
        current_code_snippet="def process_data(data: str) -> str:\n    return data.strip()",
        code_changed=True,
        pr_number=123,
        repo_name="owner/repo",
    )


@pytest.fixture
def mock_run_context(conversation_deps):
    """Create mock RunContext with ConversationDependencies."""
    context = MagicMock(spec=RunContext)
    context.deps = conversation_deps
    return context


# === TOOL TESTS ===


class TestSearchCodingStandards:
    """Tests for search_coding_standards tool."""

    @pytest.mark.asyncio
    async def test_search_coding_standards_success(self, mock_run_context):
        """Test successful search of coding standards."""
        with patch("src.agents.conversation_agent.rag_service") as mock_rag:
            mock_rag.is_available.return_value = True
            mock_rag.search_style_guides = AsyncMock(
                return_value={
                    "results": [
                        {
                            "content": "PEP 484 -- Type Hints",
                            "source": "PEP 484",
                            "score": 0.95,
                        }
                    ]
                }
            )

            result = await search_coding_standards(
                mock_run_context, query="type hints", language="python"
            )

            assert isinstance(result, str)
            assert "PEP 484" in result or "results" in result
            mock_rag.search_style_guides.assert_called_once_with(
                query="type hints", language="python", top_k=3
            )

    @pytest.mark.asyncio
    async def test_search_coding_standards_rag_unavailable(self, mock_run_context):
        """Test search when RAG service is unavailable."""
        with patch("src.agents.conversation_agent.rag_service") as mock_rag:
            mock_rag.is_available.return_value = False

            result = await search_coding_standards(
                mock_run_context, query="error handling", language="javascript"
            )

            assert result == "Unable to search coding standards at this time."
            mock_rag.search_style_guides.assert_not_called()


class TestGetCodeContext:
    """Tests for get_code_context tool."""

    def test_get_code_context_current(self, mock_run_context):
        """Test fetching current code snippet."""
        result = get_code_context(mock_run_context, use_current=True)

        assert "```" in result
        assert "def process_data(data: str) -> str:" in result

    def test_get_code_context_original(self, mock_run_context):
        """Test fetching original code snippet."""
        result = get_code_context(mock_run_context, use_current=False)

        assert "```" in result
        assert "def process_data(data):" in result

    def test_get_code_context_missing_current(self, mock_run_context):
        """Test when current code is not available."""
        mock_run_context.deps.current_code_snippet = None

        result = get_code_context(mock_run_context, use_current=True)

        assert "[Code not available" in result

    def test_get_code_context_missing_original(self, mock_run_context):
        """Test when original code is not available."""
        mock_run_context.deps.original_code_snippet = None

        result = get_code_context(mock_run_context, use_current=False)

        assert "[Code not available" in result

    def test_get_code_context_both_missing(self, mock_run_context):
        """Test when both code snippets are missing."""
        mock_run_context.deps.current_code_snippet = None
        mock_run_context.deps.original_code_snippet = None

        result = get_code_context(mock_run_context, use_current=True)

        assert "[Code not available" in result


class TestCheckCodeChanges:
    """Tests for check_code_changes tool."""

    def test_check_code_changes_with_changes(self, mock_run_context):
        """Test when code has changed."""
        result = check_code_changes(mock_run_context)

        assert "Code has been updated since the original review" in result
        assert "**Original code:**" in result
        assert "**Current code:**" in result
        assert "def process_data(data):" in result
        assert "def process_data(data: str) -> str:" in result

    def test_check_code_changes_no_changes(self, mock_run_context):
        """Test when code has not changed."""
        mock_run_context.deps.code_changed = False

        result = check_code_changes(mock_run_context)

        assert result == "Code appears unchanged since the original review."

    def test_check_code_changes_missing_snippets(self, mock_run_context):
        """Test when code snippets are missing."""
        mock_run_context.deps.code_changed = True
        mock_run_context.deps.original_code_snippet = None

        result = check_code_changes(mock_run_context)

        assert result == "Code has been modified, but details are not available."


# === VALIDATION TESTS ===


class TestValidateConversationResponse:
    """Tests for validate_conversation_response function."""

    def test_validate_normal_response(self):
        """Test validation of normal response."""
        response = "This is a helpful response to the user's question."
        result = validate_conversation_response(response)

        assert result == response

    def test_validate_empty_response(self):
        """Test validation of empty response."""
        result = validate_conversation_response("")

        assert "I encountered an issue" in result

    def test_validate_whitespace_only_response(self):
        """Test validation of whitespace-only response."""
        result = validate_conversation_response("   \n\t  ")

        assert "I encountered an issue" in result

    def test_validate_long_response_truncation(self):
        """Test truncation of overly long response."""
        long_response = "A" * 2500  # Exceeds 2000 char limit
        result = validate_conversation_response(long_response)

        assert len(result) <= 2050  # Some buffer for truncation message
        assert "[Response truncated due to length...]" in result

    def test_validate_response_strips_whitespace(self):
        """Test that response strips leading/trailing whitespace."""
        response = "  This has whitespace  \n"
        result = validate_conversation_response(response)

        assert result == "This has whitespace"

    def test_validate_response_at_limit(self):
        """Test response exactly at character limit."""
        response = "A" * 2000
        result = validate_conversation_response(response)

        assert len(result) == 2000
        assert "[Response truncated" not in result
