"""RAG tools for searching coding style guides."""

import logging
from typing import Any

from pydantic_ai import RunContext

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
        Dictionary with search results or error message

    Examples:
        - search_style_guides(ctx, "how to name variables", "python")
        - search_style_guides(ctx, "error handling best practices", "javascript")
        - search_style_guides(ctx, "security vulnerabilities to avoid")
    """
    if not rag_service.is_available():
        logger.warning("RAG service is not available for style guide search")
        return {
            "success": False,
            "error": "RAG service is not available. Ensure PINECONE_API_KEY is configured.",
            "results": [],
        }

    try:
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

        return {
            "success": True,
            "query": query,
            "language": language,
            "results_count": len(formatted_results),
            "results": formatted_results,
        }

    except Exception as e:
        logger.error(f"Error searching style guides: {e}")
        return {
            "success": False,
            "error": f"Failed to search style guides: {str(e)}",
            "results": [],
        }
