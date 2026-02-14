"""RAG tools for searching coding style guides."""

import logging
from typing import Any

from pydantic_ai import RunContext

from src.config.settings import settings
from src.models.dependencies import ReviewDependencies
from src.services.rag_service import rag_service

logger = logging.getLogger(__name__)


async def search_style_guides(
    ctx: RunContext[ReviewDependencies],
    query: str,
    language: str | None = None,
    top_k: int = 3,
) -> dict[str, Any]:
    """Search coding style guides using semantic similarity.

    This tool searches the RAG knowledge base for relevant coding conventions,
    style guides, and best practices based on a natural language query.

    Args:
        ctx: Run context with ReviewDependencies
        query: Natural language search query (e.g., "function naming conventions")
        language: Optional language filter (e.g., "python", "javascript", "go")
        top_k: Number of results to return (default: 3)

    Returns:
        Dictionary with search results

    Raises:
        RuntimeError: If RAG service is not available
        Exception: If search fails

    Examples:
        - search_style_guides(ctx, "how to name variables", "python")
        - search_style_guides(ctx, "error handling best practices", "javascript")
        - search_style_guides(ctx, "security vulnerabilities to avoid")
    """
    if not rag_service.is_available():
        raise RuntimeError(
            "RAG service is not available. Ensure PINECONE_API_KEY is configured."
        )

    # Search the knowledge base
    results = await rag_service.search_style_guides(
        query=query,
        language=language,
        top_k=top_k,
    )

    if not results:
        logger.info(
            f"No style guide results found for query='{query}', language={language}"
        )
        return {
            "success": True,
            "message": f"No relevant style guides found for '{query}'",
            "results": [],
            "max_similarity": 0.0,
            "confidence": "low",
        }

    # Format results for agent consumption
    formatted_results = []
    for result in results:
        formatted_results.append(
            {
                "content": result["content"],
                "source": result["metadata"].get("source", "Unknown"),
                "language": result["metadata"].get("language", "Unknown"),
                "document_type": result["metadata"].get("document_type", "unknown"),
                "url": result["metadata"].get("url"),
                "similarity": round(result["similarity"], 3),
            }
        )

    logger.info(
        f"Found {len(formatted_results)} style guide results for query='{query}', language={language}"
    )

    # Compute max_similarity and confidence level
    max_similarity = max((r["similarity"] for r in formatted_results), default=0.0)

    if max_similarity >= settings.rag_confidence_threshold:
        confidence = "high"
    elif max_similarity >= settings.rag_min_similarity:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "success": True,
        "query": query,
        "language": language,
        "results_count": len(formatted_results),
        "results": formatted_results,
        "max_similarity": max_similarity,
        "confidence": confidence,
    }
