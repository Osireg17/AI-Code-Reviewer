"""Unit tests for codebase search tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.codebase_search_tools import search_codebase


@pytest.mark.asyncio
@patch("src.tools.codebase_search_tools.codebase_index_service")
async def test_search_codebase_success_semantic(mock_codebase_index_service):
    """Test successful codebase search in semantic mode."""
    mock_codebase_index_service.is_available.return_value = True

    # Setup the mock codebase index service search response
    mock_codebase_index_service.search_codebase = AsyncMock(
        return_value=[
            {
                "function_name": "my_func",
                "file_path": "src/main.py",
                "signature": "def my_func():",
                "calls": [],
                "score": 0.85,
            }
        ]
    )

    ctx = MagicMock()
    ctx.deps.repo_full_name = "test-owner/test-repo"
    ctx.deps._cache = {}

    result = await search_codebase(
        ctx, "my_func", mode="semantic", language="python", top_k=5
    )

    assert result["success"] is True
    assert result["mode"] == "semantic"
    assert result["query"] == "my_func"
    assert result["results_count"] == 1
    assert len(result["results"]) == 1
    assert result["results"][0]["function_name"] == "my_func"
    assert result["results"][0]["file_path"] == "src/main.py"
    assert result["results"][0]["signature"] == "def my_func():"
    assert result["results"][0]["score"] == 0.85

    # Verify codebase index service search was called with correct namespace and mode
    mock_codebase_index_service.search_codebase.assert_called_once_with(
        query="my_func",
        namespace="test-owner__test-repo",
        mode="semantic",
        language="python",
        top_k=5,
    )


@pytest.mark.asyncio
@patch("src.tools.codebase_search_tools.codebase_index_service")
async def test_search_codebase_success_exact_call(mock_codebase_index_service):
    """Test successful codebase search in exact_call mode."""
    mock_codebase_index_service.is_available.return_value = True

    mock_codebase_index_service.search_codebase = AsyncMock(
        return_value=[
            {
                "function_name": "checkout",
                "file_path": "src/handlers/checkout.py",
                "signature": "async def checkout(cart: Cart) -> Order",
                "calls": ["process_payment", "send_receipt"],
                "score": 0.95,
            }
        ]
    )

    ctx = MagicMock()
    ctx.deps.repo_full_name = "test-owner/test-repo"
    ctx.deps._cache = {}

    result = await search_codebase(ctx, "process_payment", mode="exact_call", top_k=5)

    assert result["success"] is True
    assert result["mode"] == "exact_call"
    assert result["query"] == "process_payment"
    assert result["results_count"] == 1
    assert len(result["results"]) == 1
    assert result["results"][0]["function_name"] == "checkout"
    assert result["results"][0]["file_path"] == "src/handlers/checkout.py"
    assert (
        result["results"][0]["signature"] == "async def checkout(cart: Cart) -> Order"
    )
    assert result["results"][0]["calls"] == ["process_payment", "send_receipt"]
    assert result["results"][0]["score"] == 0.95


@pytest.mark.asyncio
@patch("src.tools.codebase_search_tools.codebase_index_service")
async def test_search_codebase_service_unavailable(mock_codebase_index_service):
    """Test search when codebase index service is unavailable."""
    mock_codebase_index_service.is_available.return_value = False

    ctx = MagicMock()

    result = await search_codebase(ctx, "test query")

    assert result["success"] is False
    assert result["error"] == "Codebase index unavailable"
    assert result["results"] == []


@pytest.mark.asyncio
@patch("src.tools.codebase_search_tools.codebase_index_service")
async def test_search_codebase_invalid_mode(mock_codebase_index_service):
    """Test search with an invalid mode."""
    ctx = MagicMock()

    result = await search_codebase(ctx, "test query", mode="fuzzy")

    assert result["success"] is False
    assert result["error"] == "Invalid mode 'fuzzy'. Use 'semantic' or 'exact_call'."
    assert result["results"] == []
