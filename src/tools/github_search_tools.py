import logging
from typing import Any, cast

from pydantic_ai import RunContext

from src.models.dependencies import ReviewDependencies
from src.services.github_search_service import search_code

logger = logging.getLogger(__name__)


async def search_codebase(
    ctx: RunContext[ReviewDependencies],
    query: str,
    language_filter: str | None = None,
) -> dict[str, Any]:
    cache_key = f"search:{query}:{language_filter}"
    if cache_key in ctx.deps._cache:
        logger.debug(f"returning cached search results for '{query}'")
        return cast(dict[str, Any], ctx.deps._cache[cache_key])

    raw_results = await search_code(
        query=query,
        repo_full_name=ctx.deps.repo_full_name,
        http_client=ctx.deps.http_client,
        language_filter=language_filter,
    )

    formatted = {
        "success": True,
        "query": query,
        "results_count": len(raw_results),
        "results": raw_results,
    }

    ctx.deps._cache[cache_key] = formatted

    logger.info(
        f"Code search for '{query}': found {len(raw_results)} results in "
        f"{ctx.deps.repo_full_name}"
    )

    return formatted
