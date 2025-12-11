"""Unit tests for RAG service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.rag_service import RAGService, rag_service


def test_format_results_for_context_empty():
    """Test formatting empty results list."""
    results = []
    formatted = rag_service.format_results_for_context(results)
    assert formatted == "No relevant style guide information found."


def test_format_results_for_context_single_result():
    """Test formatting single result."""
    results = [
        {
            "metadata": {"source": "Google Style", "language": "python"},
            "content": "Use snake_case for functions.",
            "similarity": 0.85,
        }
    ]
    formatted = rag_service.format_results_for_context(results)

    expected = (
        "[Source 1: Google Style (python) - Relevance: 85.00%]\n"
        "Use snake_case for functions.\n"
    )
    assert formatted == expected


def test_format_results_for_context_multiple_results():
    """Test formatting multiple results."""
    results = [
        {
            "metadata": {"source": "Google Style", "language": "python"},
            "content": "Use snake_case.",
            "similarity": 0.9,
        },
        {
            "metadata": {"source": "PEP 8", "language": "python"},
            "content": "Indent with 4 spaces.",
            "similarity": 0.8,
        },
    ]
    formatted = rag_service.format_results_for_context(results)

    expected_part1 = (
        "[Source 1: Google Style (python) - Relevance: 90.00%]\nUse snake_case.\n"
    )
    expected_part2 = (
        "[Source 2: PEP 8 (python) - Relevance: 80.00%]\nIndent with 4 spaces.\n"
    )
    expected = f"{expected_part1}\n---\n{expected_part2}"

    assert formatted == expected


def test_format_results_for_context_missing_metadata():
    """Test formatting results with missing metadata."""
    results = [
        {
            "metadata": {},
            "content": "Some content.",
            "similarity": 0.5,
        }
    ]
    formatted = rag_service.format_results_for_context(results)

    expected = "[Source 1: Unknown (Unknown) - Relevance: 50.00%]\nSome content.\n"
    assert formatted == expected


@patch("src.services.rag_service.settings")
def test_rag_service_disabled(mock_settings):
    """Test RAG service when disabled."""
    mock_settings.rag_enabled = False
    service = RAGService()
    assert not service.is_available()
    assert service.pc is None
    assert service.index is None
    assert service.embeddings is None


@patch("src.services.rag_service.settings")
def test_rag_service_missing_api_key(mock_settings):
    """Test RAG service with missing API key."""
    mock_settings.rag_enabled = True
    mock_settings.pinecone_api_key = None
    service = RAGService()
    assert not service.is_available()


@patch("src.services.rag_service.settings")
@patch("src.services.rag_service.Pinecone")
def test_rag_service_index_not_exists(mock_pinecone, mock_settings):
    """Test RAG service when index doesn't exist."""
    mock_settings.rag_enabled = True
    mock_settings.pinecone_api_key = "test-key"
    mock_settings.pinecone_index_name = "missing-index"

    mock_pc = MagicMock()
    mock_pinecone.return_value = mock_pc
    mock_pc.list_indexes.return_value.indexes = [MagicMock(name="other-index")]

    service = RAGService()
    assert not service.is_available()


@pytest.mark.asyncio
async def test_search_style_guides_service_unavailable():
    """Test search when service is unavailable."""
    with patch.object(rag_service, "is_available", return_value=False):
        results = await rag_service.search_style_guides("test query")
        assert results == []


@pytest.mark.asyncio
@patch("src.services.rag_service.PineconeVectorStore")
async def test_search_style_guides_success(mock_vector_store):
    """Test successful style guide search."""
    with patch.object(rag_service, "is_available", return_value=True):
        mock_doc = MagicMock()
        mock_doc.page_content = "Use snake_case"
        mock_doc.metadata = {"source": "pep8", "language": "python"}

        mock_store = AsyncMock()
        mock_store.asimilarity_search_with_score = AsyncMock(
            return_value=[(mock_doc, 0.2)]
        )
        mock_vector_store.return_value = mock_store

        with patch("src.services.rag_service.settings") as mock_settings:
            mock_settings.rag_top_k = 3
            mock_settings.rag_min_similarity = 0.5

            results = await rag_service.search_style_guides(
                "naming conventions", "python", 3
            )

            assert len(results) == 1
            assert results[0]["content"] == "Use snake_case"
            assert results[0]["similarity"] == 0.8


@pytest.mark.asyncio
@patch("src.services.rag_service.PineconeVectorStore")
async def test_search_style_guides_below_threshold(mock_vector_store):
    """Test search filtering results below similarity threshold."""
    with patch.object(rag_service, "is_available", return_value=True):
        mock_doc = MagicMock()
        mock_doc.page_content = "Some content"
        mock_doc.metadata = {"source": "test", "language": "python"}

        mock_store = AsyncMock()
        mock_store.asimilarity_search_with_score = AsyncMock(
            return_value=[(mock_doc, 0.6)]
        )
        mock_vector_store.return_value = mock_store

        with patch("src.services.rag_service.settings") as mock_settings:
            mock_settings.rag_top_k = 3
            mock_settings.rag_min_similarity = 0.5

            results = await rag_service.search_style_guides("test", "python")

            assert len(results) == 0


@pytest.mark.asyncio
async def test_search_style_guides_error_handling():
    """Test error handling in search."""
    with (
        patch.object(rag_service, "is_available", return_value=True),
        patch(
            "src.services.rag_service.PineconeVectorStore",
            side_effect=Exception("Test error"),
        ),
    ):
        results = await rag_service.search_style_guides("test")
        assert results == []
