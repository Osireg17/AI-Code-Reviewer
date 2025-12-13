"""Unit tests for RAG tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.rag_tools import search_style_guides


@pytest.mark.asyncio
@patch("src.tools.rag_tools.rag_service")
async def test_search_style_guides_success(mock_rag_service):
    """Test successful style guide search."""
    mock_rag_service.is_available.return_value = True
    mock_rag_service.search_style_guides = AsyncMock(
        return_value=[
            {
                "content": "Use snake_case",
                "metadata": {
                    "source": "pep8",
                    "language": "python",
                    "document_type": "style_guide",
                    "url": "https://pep8.org",
                },
                "similarity": 0.85,
            }
        ]
    )

    ctx = MagicMock()
    result = await search_style_guides(ctx, "naming conventions", "python", 3)

    assert result["success"] is True
    assert result["query"] == "naming conventions"
    assert result["language"] == "python"
    assert result["results_count"] == 1
    assert len(result["results"]) == 1
    assert result["results"][0]["content"] == "Use snake_case"
    assert result["results"][0]["source"] == "pep8"
    assert result["results"][0]["similarity"] == 0.85


@pytest.mark.asyncio
@patch("src.tools.rag_tools.rag_service")
async def test_search_style_guides_no_results(mock_rag_service):
    """Test search with no results."""
    mock_rag_service.is_available.return_value = True
    mock_rag_service.search_style_guides = AsyncMock(return_value=[])

    ctx = MagicMock()
    result = await search_style_guides(ctx, "nonexistent query", "python")

    assert result["success"] is True
    assert result["message"] == "No relevant style guides found for 'nonexistent query'"
    assert result["results"] == []


@pytest.mark.asyncio
@patch("src.tools.rag_tools.rag_service")
async def test_search_style_guides_service_unavailable(mock_rag_service):
    """Test search when RAG service is unavailable."""
    mock_rag_service.is_available.return_value = False

    ctx = MagicMock()

    with pytest.raises(RuntimeError) as exc_info:
        await search_style_guides(ctx, "test query")

    assert "RAG service is not available" in str(exc_info.value)


@pytest.mark.asyncio
@patch("src.tools.rag_tools.rag_service")
async def test_search_style_guides_error_handling(mock_rag_service):
    """Test error handling in search."""
    mock_rag_service.is_available.return_value = True
    mock_rag_service.search_style_guides = AsyncMock(
        side_effect=Exception("Test error")
    )

    ctx = MagicMock()

    with pytest.raises(Exception) as exc_info:
        await search_style_guides(ctx, "test query")

    assert "Test error" in str(exc_info.value)


@pytest.mark.asyncio
@patch("src.tools.rag_tools.rag_service")
async def test_search_style_guides_no_language_filter(mock_rag_service):
    """Test search without language filter."""
    mock_rag_service.is_available.return_value = True
    mock_rag_service.search_style_guides = AsyncMock(
        return_value=[
            {
                "content": "Security best practice",
                "metadata": {
                    "source": "owasp",
                    "language": "cross-language",
                    "document_type": "security",
                },
                "similarity": 0.9,
            }
        ]
    )

    ctx = MagicMock()
    result = await search_style_guides(ctx, "security", None, 5)

    assert result["success"] is True
    assert result["language"] is None
    mock_rag_service.search_style_guides.assert_called_once_with(
        query="security", language=None, top_k=5
    )


@pytest.mark.asyncio
@patch("src.tools.rag_tools.rag_service")
async def test_search_style_guides_metadata_handling(mock_rag_service):
    """Test proper handling of metadata fields."""
    mock_rag_service.is_available.return_value = True
    mock_rag_service.search_style_guides = AsyncMock(
        return_value=[
            {
                "content": "Test content",
                "metadata": {
                    "source": "test-source",
                    "language": "python",
                    "document_type": "reference",
                },
                "similarity": 0.75,
            }
        ]
    )

    ctx = MagicMock()
    result = await search_style_guides(ctx, "test", "python")

    assert result["results"][0]["source"] == "test-source"
    assert result["results"][0]["language"] == "python"
    assert result["results"][0]["document_type"] == "reference"
    assert result["results"][0]["url"] is None
