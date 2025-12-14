"""RAG service for retrieving coding style guides using Pinecone + LangChain."""

import logging
from collections.abc import Callable
from typing import Any

from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone

from src.config.settings import settings

logger = logging.getLogger(__name__)


class RAGService:
    """Service for retrieval-augmented generation using style guides."""

    def __init__(self) -> None:
        """Initialize RAG service with Pinecone and OpenAI embeddings."""
        if not settings.rag_enabled:
            logger.info("RAG is disabled in settings")
            self.pc = None
            self.index = None
            self.embeddings = None
            return

        if not settings.pinecone_api_key:
            logger.warning(
                "Pinecone API key not found - RAG service will be unavailable"
            )
            self.pc = None
            self.index = None
            self.embeddings = None
            return

        try:
            # Initialize Pinecone client
            self.pc = Pinecone(api_key=settings.pinecone_api_key)

            # Verify index exists
            existing_indexes = [idx.name for idx in self.pc.list_indexes().indexes]
            if settings.pinecone_index_name not in existing_indexes:
                logger.error(
                    f"Pinecone index '{settings.pinecone_index_name}' does not exist. "
                    f"Available indexes: {existing_indexes}. "
                    f"Run 'python scripts/setup_pinecone.py' to create it."
                )
                self.pc = None
                self.index = None
                self.embeddings = None
                return

            self.index = self.pc.Index(settings.pinecone_index_name)

            api_key_callable: Callable[[], str] | None = None
            if settings.openai_api_key:

                def api_key_callable() -> str:
                    assert settings.openai_api_key is not None
                    return settings.openai_api_key

            self.embeddings = OpenAIEmbeddings(
                model=settings.embedding_model,
                api_key=api_key_callable,
            )

            logger.info(
                f"RAG service initialized with index: {settings.pinecone_index_name}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize RAG service: {e}")
            self.pc = None
            self.index = None
            self.embeddings = None

    def is_available(self) -> bool:
        """Check if RAG service is available."""
        return (
            settings.rag_enabled
            and self.pc is not None
            and self.index is not None
            and self.embeddings is not None
        )

    async def search_style_guides(
        self,
        query: str,
        language: str | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search style guides using semantic similarity.

        Args:
            query: Natural language query (e.g., "function naming conventions")
            language: Filter by language (e.g., "python", "javascript")
            top_k: Number of results to return (default from settings)

        Returns:
            List of relevant chunks with content, metadata, and similarity score
        """
        if not self.is_available():
            logger.warning("RAG service is not available")
            return []

        if top_k is None:
            top_k = settings.rag_top_k

        # Create vector store with namespace filtering
        namespace = language or None

        vector_store = PineconeVectorStore(
            index=self.index,
            embedding=self.embeddings,
            namespace=namespace,
        )

        # LangChain handles: embedding query + similarity search
        results = await vector_store.asimilarity_search_with_score(
            query=query,
            k=top_k,
        )

        # Format results
        formatted_results = []
        for doc, score in results:
            # Convert distance to similarity (lower distance = higher similarity)
            similarity = 1 - score

            # Filter by minimum similarity threshold
            if similarity >= settings.rag_min_similarity:
                formatted_results.append(
                    {
                        "content": doc.page_content,
                        "metadata": doc.metadata,
                        "similarity": similarity,
                    }
                )

        logger.info(
            f"RAG search: query='{query[:50]}...', language={language}, "
            f"found={len(formatted_results)} results"
        )

        return formatted_results

    def format_results_for_context(self, results: list[dict[str, Any]]) -> str:
        """Format search results into context string for LLM.

        Args:
            results: List of search results from search_style_guides()

        Returns:
            Formatted string with sources and content for LLM context
        """
        if not results:
            return "No relevant style guide information found."

        context_parts = []
        for i, result in enumerate(results, 1):
            metadata = result["metadata"]
            source = f"{metadata.get('source', 'Unknown')} ({metadata.get('language', 'Unknown')})"
            content = result["content"]
            similarity = result["similarity"]

            # Add source reference with relevance score
            context_parts.append(
                f"[Source {i}: {source} - Relevance: {similarity:.2%}]\n{content}\n"
            )

        return "\n---\n".join(context_parts)


# Singleton instance
rag_service = RAGService()
