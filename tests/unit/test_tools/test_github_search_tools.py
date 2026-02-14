"""Unit tests for GitHub code search tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.tools.github_search_tools import search_codebase


def _make_ctx():
    ctx = MagicMock()
    ctx.deps.repo_full_name = "owner/repo"
    ctx.deps.http_client = AsyncMock()
    ctx.deps._cache = {}
    return ctx


@pytest.mark.asyncio
@patch("src.tools.github_search_tools.search_code")
async def test_search_codebase_success(mock_search_code):
    mock_search_code.return_value = [
        {
            "file_path": "src/utils.py",
            "matched_lines": ["def helper():"],
            "url": "https://...",
        }
    ]
    ctx = _make_ctx()
    result = await search_codebase(ctx, "helper function")
    assert result["success"] is True
    assert result["query"] == "helper function"
    assert result["results_count"] == 1
    assert result["results"][0]["file_path"] == "src/utils.py"
    mock_search_code.assert_called_once_with(
        query="helper function",
        repo_full_name="owner/repo",
        http_client=ctx.deps.http_client,
        language_filter=None,
    )


@pytest.mark.asyncio
@patch("src.tools.github_search_tools.search_code")
async def test_search_codebase_with_language_filter(mock_search_code):
    mock_search_code.return_value = [
        {"file_path": "src/utils.py", "matched_lines": [], "url": ""}
    ]
    ctx = _make_ctx()
    await search_codebase(ctx, "naming convention", language_filter="python")
    mock_search_code.assert_called_once_with(
        query="naming convention",
        repo_full_name="owner/repo",
        http_client=ctx.deps.http_client,
        language_filter="python",
    )


@pytest.mark.asyncio
@patch("src.tools.github_search_tools.search_code")
async def test_search_codebase_caches_result(mock_search_code):
    mock_search_code.return_value = [
        {"file_path": "a.py", "matched_lines": [], "url": ""}
    ]
    ctx = _make_ctx()
    result1 = await search_codebase(ctx, "error handling", language_filter="python")
    result2 = await search_codebase(ctx, "error handling", language_filter="python")
    assert result1 == result2
    mock_search_code.assert_called_once()


@pytest.mark.asyncio
@patch("src.tools.github_search_tools.search_code")
async def test_search_codebase_cache_key_includes_language(mock_search_code):
    mock_search_code.return_value = [
        {"file_path": "a.py", "matched_lines": [], "url": ""}
    ]
    ctx = _make_ctx()
    await search_codebase(ctx, "error handling", language_filter="python")
    await search_codebase(ctx, "error handling", language_filter="go")
    assert mock_search_code.call_count == 2
    mock_search_code.assert_any_call(
        query="error handling",
        repo_full_name="owner/repo",
        http_client=ctx.deps.http_client,
        language_filter="python",
    )
    mock_search_code.assert_any_call(
        query="error handling",
        repo_full_name="owner/repo",
        http_client=ctx.deps.http_client,
        language_filter="go",
    )


@pytest.mark.asyncio
@patch("src.tools.github_search_tools.search_code")
async def test_search_codebase_empty_results(mock_search_code):
    mock_search_code.return_value = []
    ctx = _make_ctx()
    result = await search_codebase(ctx, "nonexistent pattern")
    assert result["success"] is True
    assert result["results_count"] == 0
    assert result["results"] == []


@pytest.mark.asyncio
@patch("src.tools.github_search_tools.search_code")
async def test_search_codebase_service_error_propagates(mock_search_code):
    mock_search_code.side_effect = ValueError("auth not configured")
    ctx = _make_ctx()
    with pytest.raises(ValueError, match="auth not configured"):
        await search_codebase(ctx, "query")


@pytest.mark.asyncio
@patch("src.tools.github_search_tools.search_code")
async def test_search_codebase_http_error_propagates(mock_search_code):
    mock_search_code.side_effect = httpx.ConnectError("timeout")
    ctx = _make_ctx()
    with pytest.raises(httpx.ConnectError, match="timeout"):
        await search_codebase(ctx, "query")


@pytest.mark.asyncio
@patch("src.tools.github_search_tools.search_code")
async def test_search_codebase_error_not_cached(mock_search_code):
    mock_search_code.side_effect = ValueError("fail")
    ctx = _make_ctx()
    with pytest.raises(ValueError, match="fail"):
        await search_codebase(ctx, "query")
    assert ctx.deps._cache == {}
