"""Unit tests for GitHub Code Search service."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.services.github_search_service import _parse_search_results, search_code

# --- Helpers ---


def _mock_auth():
    """Create a mock GitHubAppAuth that returns a test token."""
    mock_auth = MagicMock()
    mock_auth.get_installation_access_token = AsyncMock(return_value="test-token")
    return mock_auth


def _mock_http_response(status_code: int, json_body: dict | None = None):
    """Create a mock httpx response."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = status_code
    mock_response.json.return_value = json_body or {"items": []}
    return mock_response


def _mock_http_client(response):
    """Create a mock AsyncClient whose .get() returns the given response."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = response
    return client


# --- search_code tests ---


@pytest.mark.asyncio
@patch("src.services.github_search_service.github_search_rate_limiter")
@patch("src.services.github_search_service.get_github_app_auth")
async def test_search_code_success(mock_get_auth, mock_rate_limiter):
    """Verify search_code returns formatted results on a 200 response."""
    mock_get_auth.return_value = _mock_auth()
    mock_rate_limiter.acquire = AsyncMock()

    response = _mock_http_response(
        200,
        {
            "items": [
                {
                    "path": "src/utils.py",
                    "html_url": "https://github.com/owner/repo/blob/main/src/utils.py",
                    "text_matches": [{"fragment": "def snake_case_function():"}],
                }
            ]
        },
    )
    client = _mock_http_client(response)

    results = await search_code("snake_case", "owner/repo", client)

    assert len(results) == 1
    assert results[0]["file_path"] == "src/utils.py"
    assert "def snake_case_function():" in results[0]["matched_lines"]
    assert results[0]["url"] == "https://github.com/owner/repo/blob/main/src/utils.py"

    # Verify the HTTP call was made with correct params
    client.get.assert_called_once()
    call_kwargs = client.get.call_args
    assert call_kwargs[1]["params"]["q"] == "snake_case repo:owner/repo"


@pytest.mark.asyncio
@patch("src.services.github_search_service.github_search_rate_limiter")
@patch("src.services.github_search_service.get_github_app_auth")
async def test_search_code_with_language_filter(mock_get_auth, mock_rate_limiter):
    """Verify language filter is appended to the search query."""
    mock_get_auth.return_value = _mock_auth()
    mock_rate_limiter.acquire = AsyncMock()

    client = _mock_http_client(_mock_http_response(200))

    await search_code("error handling", "owner/repo", client, language_filter="python")

    call_kwargs = client.get.call_args
    assert "language:python" in call_kwargs[1]["params"]["q"]


@pytest.mark.asyncio
@patch("src.services.github_search_service.github_search_rate_limiter")
@patch("src.services.github_search_service.get_github_app_auth")
async def test_search_code_rate_limited_403(mock_get_auth, mock_rate_limiter):
    """Verify 403 response returns empty list."""
    mock_get_auth.return_value = _mock_auth()
    mock_rate_limiter.acquire = AsyncMock()

    client = _mock_http_client(_mock_http_response(403))

    results = await search_code("query", "owner/repo", client)

    assert results == []


@pytest.mark.asyncio
@patch("src.services.github_search_service.github_search_rate_limiter")
@patch("src.services.github_search_service.get_github_app_auth")
async def test_search_code_rate_limited_429(mock_get_auth, mock_rate_limiter):
    """Verify 429 response returns empty list."""
    mock_get_auth.return_value = _mock_auth()
    mock_rate_limiter.acquire = AsyncMock()

    client = _mock_http_client(_mock_http_response(429))

    results = await search_code("query", "owner/repo", client)

    assert results == []


@pytest.mark.asyncio
@patch("src.services.github_search_service.github_search_rate_limiter")
@patch("src.services.github_search_service.get_github_app_auth")
async def test_search_code_server_error(mock_get_auth, mock_rate_limiter):
    """Verify 5xx response returns empty list."""
    mock_get_auth.return_value = _mock_auth()
    mock_rate_limiter.acquire = AsyncMock()

    client = _mock_http_client(_mock_http_response(500))

    results = await search_code("query", "owner/repo", client)

    assert results == []


@pytest.mark.asyncio
@patch("src.services.github_search_service.github_search_rate_limiter")
@patch("src.services.github_search_service.get_github_app_auth")
async def test_search_code_unexpected_status(mock_get_auth, mock_rate_limiter):
    """Verify non-200 non-rate-limit non-5xx status returns empty list."""
    mock_get_auth.return_value = _mock_auth()
    mock_rate_limiter.acquire = AsyncMock()

    client = _mock_http_client(_mock_http_response(422))

    results = await search_code("query", "owner/repo", client)

    assert results == []


@pytest.mark.asyncio
@patch("src.services.github_search_service.github_search_rate_limiter")
@patch("src.services.github_search_service.get_github_app_auth")
async def test_search_code_auth_error_propagates(mock_get_auth, mock_rate_limiter):
    """Verify auth errors propagate (not caught by search_code)."""
    mock_auth = MagicMock()
    mock_auth.get_installation_access_token = AsyncMock(
        side_effect=ValueError("GitHub App ID not configured")
    )
    mock_get_auth.return_value = mock_auth
    mock_rate_limiter.acquire = AsyncMock()

    client = AsyncMock(spec=httpx.AsyncClient)

    with pytest.raises(ValueError, match="GitHub App ID not configured"):
        await search_code("query", "owner/repo", client)

    client.get.assert_not_called()


@pytest.mark.asyncio
@patch("src.services.github_search_service.github_search_rate_limiter")
@patch("src.services.github_search_service.get_github_app_auth")
async def test_search_code_http_error_propagates(mock_get_auth, mock_rate_limiter):
    """Verify httpx errors propagate (not caught by search_code)."""
    mock_get_auth.return_value = _mock_auth()
    mock_rate_limiter.acquire = AsyncMock()

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.side_effect = httpx.ConnectError("Connection refused")

    with pytest.raises(httpx.ConnectError):
        await search_code("query", "owner/repo", client)


@pytest.mark.asyncio
@patch("src.services.github_search_service.github_search_rate_limiter")
@patch("src.services.github_search_service.get_github_app_auth")
async def test_search_code_max_results_capped(mock_get_auth, mock_rate_limiter):
    """Verify max_results is capped at 100 (GitHub API limit)."""
    mock_get_auth.return_value = _mock_auth()
    mock_rate_limiter.acquire = AsyncMock()

    client = _mock_http_client(_mock_http_response(200))

    await search_code("query", "owner/repo", client, max_results=200)

    call_kwargs = client.get.call_args
    assert call_kwargs[1]["params"]["per_page"] == 100


@pytest.mark.asyncio
@patch("src.services.github_search_service.github_search_rate_limiter")
@patch("src.services.github_search_service.get_github_app_auth")
async def test_search_code_rate_limiter_acquired(mock_get_auth, mock_rate_limiter):
    """Verify rate limiter acquire() is called before the HTTP request."""
    mock_get_auth.return_value = _mock_auth()
    mock_rate_limiter.acquire = AsyncMock()

    client = _mock_http_client(_mock_http_response(200))

    await search_code("query", "owner/repo", client)

    mock_rate_limiter.acquire.assert_called_once()


# --- _parse_search_results tests ---


def test_parse_search_results_multiple_items():
    """Verify _parse_search_results handles multiple items with text matches."""
    data = {
        "items": [
            {
                "path": "a.py",
                "html_url": "url1",
                "text_matches": [{"fragment": "code1"}],
            },
            {
                "path": "b.py",
                "html_url": "url2",
                "text_matches": [{"fragment": "code2"}],
            },
            {"path": "c.py", "html_url": "url3", "text_matches": []},
        ]
    }

    results = _parse_search_results(data, max_results=3)

    assert len(results) == 3
    assert results[0]["file_path"] == "a.py"
    assert results[0]["matched_lines"] == ["code1"]
    assert results[2]["matched_lines"] == []


def test_parse_search_results_deduplicates_fragments():
    """Verify duplicate fragments within one item are deduplicated."""
    data = {
        "items": [
            {
                "path": "a.py",
                "html_url": "url1",
                "text_matches": [
                    {"fragment": "same code"},
                    {"fragment": "same code"},
                    {"fragment": "different code"},
                ],
            }
        ]
    }

    results = _parse_search_results(data, max_results=5)

    assert results[0]["matched_lines"] == ["same code", "different code"]


def test_parse_search_results_respects_max():
    """Verify max_results caps the number of items returned."""
    data = {
        "items": [
            {"path": "a.py", "html_url": "url1", "text_matches": []},
            {"path": "b.py", "html_url": "url2", "text_matches": []},
            {"path": "c.py", "html_url": "url3", "text_matches": []},
        ]
    }

    results = _parse_search_results(data, max_results=2)

    assert len(results) == 2


def test_parse_search_results_empty():
    """Verify empty items list returns empty results."""
    data = {"items": []}

    results = _parse_search_results(data, max_results=5)

    assert results == []
