"""RAG tools for searching codebases."""

import logging
from typing import Any, cast

from pydantic_ai import RunContext

from src.models.dependencies import ReviewDependencies
from src.services.codebase_index_service import codebase_index_service

logger = logging.getLogger(__name__)


async def search_codebase(
    ctx: RunContext[ReviewDependencies],
    query: str,
    mode: str = "semantic",  # "semantic" | "exact_call"
    language: str | None = None,
    top_k: int = 5,
) -> dict:
    """Search the codebase semantic index for matching code patterns.

    Args:
        ctx: Run context with ReviewDependencies
        query: Search query
        mode: Search mode ("semantic" or "exact_call")
        language: Optional language filter
        top_k: Number of results to return

    Returns:
        Dict response formatted per specification
    """
    if mode not in ("semantic", "exact_call"):
        return {
            "success": False,
            "error": f"Invalid mode '{mode}'. Use 'semantic' or 'exact_call'.",
            "results": [],
        }

    if not codebase_index_service.is_available():
        return {
            "success": False,
            "error": "Codebase index unavailable",
            "results": [],
        }

    namespace = ctx.deps.repo_full_name.lower().replace("/", "__")
    cache_key = f"codebase_search:{namespace}:{query}:{mode}:{language}:{top_k}"
    if cache_key in ctx.deps._cache:
        logger.debug(f"Returning cached codebase search results for {cache_key}")
        return cast(dict[Any, Any], ctx.deps._cache[cache_key])

    try:
        results = await codebase_index_service.search_codebase(
            query=query,
            namespace=namespace,
            mode=mode,
            language=language,
            top_k=top_k,
        )

        formatted_response = {
            "success": True,
            "mode": mode,
            "query": query,
            "results_count": len(results),
            "results": results,
        }

        ctx.deps._cache[cache_key] = formatted_response
        return formatted_response

    except Exception as e:
        logger.error(f"Error in search_codebase tool: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "results": [],
        }
