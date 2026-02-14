"""GitHub Code Search service with rate limiting and error handling."""

import logging
from typing import Any

import httpx

from src.config.settings import settings
from src.services.github_auth import get_github_app_auth
from src.utils.rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)

# Rate limiter for GitHub Code Search API
# GitHub's code search has a strict limit of 10 requests per minute
# TokenBucketRateLimiter(rate=10/60, capacity=3) — allow small bursts of 3
github_search_rate_limiter = TokenBucketRateLimiter(
    rate=10 / 60,  # 10 requests per minute = 0.167 requests/second
    capacity=3,  # Allow bursts of up to 3 requests
)

# GitHub API caps per_page at 100
_MAX_PER_PAGE = 100


async def search_code(
    query: str,
    repo_full_name: str,
    http_client: httpx.AsyncClient,
    language_filter: str | None = None,
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    """Search for code in a GitHub repository.

    Args:
        query: Search term (e.g., "snake_case naming", "error handling")
        repo_full_name: Repository in "owner/repo" format
        http_client: Async HTTP client for API calls
        language_filter: Optional language filter (e.g., "python", "javascript")
        max_results: Maximum results to return (default from settings)

    Returns:
        List of dicts with: file_path, matched_lines (list[str]), url

    Raises:
        ValueError: If GitHub App auth is not configured
        httpx.HTTPError: If the HTTP request fails (connection, timeout, etc.)

    Note:
        Returns empty list on rate limit (403/429) or server errors (5xx).
        Auth and network errors propagate to the caller.
    """
    if max_results is None:
        max_results = settings.github_search_max_results
    max_results = min(max_results, _MAX_PER_PAGE)

    # Acquire rate limiter token (will wait if rate-limited)
    await github_search_rate_limiter.acquire()

    # Build search query
    search_query = f"{query} repo:{repo_full_name}"
    if language_filter:
        search_query += f" language:{language_filter}"

    # Get installation token via the auth service (same source as the Github client)
    github_auth = get_github_app_auth()
    token = await github_auth.get_installation_access_token()

    # Build request headers
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.text-match+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Call GitHub Code Search API
    url = "https://api.github.com/search/code"
    params: dict[str, str | int] = {
        "q": search_query,
        "per_page": max_results,
    }

    response = await http_client.get(url, headers=headers, params=params)

    # Handle rate limiting (403/429)
    if response.status_code in (403, 429):
        logger.warning(
            f"GitHub Search: Rate limited (status={response.status_code}). "
            f"Query: '{query}', Repo: {repo_full_name}"
        )
        return []

    # Handle server errors (5xx)
    if response.status_code >= 500:
        logger.error(
            f"GitHub Search: Server error (status={response.status_code}). "
            f"Query: '{query}', Repo: {repo_full_name}"
        )
        return []

    # Handle other non-success status codes
    if response.status_code != 200:
        logger.warning(
            f"GitHub Search: Unexpected status {response.status_code}. "
            f"Query: '{query}', Repo: {repo_full_name}"
        )
        return []

    data = response.json()

    # Parse response and extract results
    results = _parse_search_results(data, max_results)

    query_display = query[:50] + "..." if len(query) > 50 else query
    logger.info(
        f"GitHub Search: query='{query_display}', repo={repo_full_name}, "
        f"found={len(results)} results"
    )

    return results


def _parse_search_results(
    data: dict[str, Any], max_results: int
) -> list[dict[str, Any]]:
    """Parse GitHub search API response into formatted results.

    Args:
        data: Raw API response data
        max_results: Maximum number of results to return

    Returns:
        List of formatted result dicts
    """
    results: list[dict[str, Any]] = []

    items = data.get("items", [])

    for item in items[:max_results]:
        file_path = item.get("path", "")
        html_url = item.get("html_url", "")

        # Extract text match fragments
        matched_lines: list[str] = []
        text_matches = item.get("text_matches", [])

        for match in text_matches:
            fragment = match.get("fragment", "")
            if fragment:
                # Clean up the fragment (remove excessive whitespace)
                fragment = fragment.strip()
                if fragment and fragment not in matched_lines:
                    matched_lines.append(fragment)

        results.append(
            {
                "file_path": file_path,
                "matched_lines": matched_lines,
                "url": html_url,
            }
        )

    return results
