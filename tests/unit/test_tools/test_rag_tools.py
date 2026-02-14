"""Unit tests for RAG tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.rag_tools import search_style_guides


@pytest.mark.asyncio
@patch("src.tools.rag_tools.settings")
@patch("src.tools.rag_tools.rag_service")
async def test_search_style_guides_success(mock_rag_service, mock_settings):
    """Test successful style guide search."""
    mock_settings.rag_confidence_threshold = 0.6
    mock_settings.rag_min_similarity = 0.4
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
    assert result["max_similarity"] == 0.85
    assert result["confidence"] == "high"


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


@pytest.mark.asyncio
@patch("src.tools.rag_tools.settings")
@patch("src.tools.rag_tools.rag_service")
async def test_search_style_guides_high_confidence(mock_rag_service, mock_settings):
    """Test high confidence when similarity >= rag_confidence_threshold."""
    mock_settings.rag_confidence_threshold = 0.6
    mock_settings.rag_min_similarity = 0.4
    mock_rag_service.is_available.return_value = True
    mock_rag_service.search_style_guides = AsyncMock(
        return_value=[
            {
                "content": "High confidence result",
                "metadata": {
                    "source": "test",
                    "language": "python",
                    "document_type": "guide",
                },
                "similarity": 0.85,
            }
        ]
    )

    ctx = MagicMock()
    result = await search_style_guides(ctx, "test query", "python")

    assert result["max_similarity"] == 0.85
    assert result["confidence"] == "high"


@pytest.mark.asyncio
@patch("src.tools.rag_tools.settings")
@patch("src.tools.rag_tools.rag_service")
async def test_search_style_guides_medium_confidence(mock_rag_service, mock_settings):
    """Test medium confidence when similarity >= rag_min_similarity but < rag_confidence_threshold."""
    mock_settings.rag_confidence_threshold = 0.6
    mock_settings.rag_min_similarity = 0.4
    mock_rag_service.is_available.return_value = True
    mock_rag_service.search_style_guides = AsyncMock(
        return_value=[
            {
                "content": "Medium confidence result",
                "metadata": {
                    "source": "test",
                    "language": "python",
                    "document_type": "guide",
                },
                "similarity": 0.5,
            }
        ]
    )

    ctx = MagicMock()
    result = await search_style_guides(ctx, "test query", "python")

    assert result["max_similarity"] == 0.5
    assert result["confidence"] == "medium"


@pytest.mark.asyncio
@patch("src.tools.rag_tools.settings")
@patch("src.tools.rag_tools.rag_service")
async def test_search_style_guides_low_confidence(mock_rag_service, mock_settings):
    """Test low confidence when similarity < rag_min_similarity."""
    mock_settings.rag_confidence_threshold = 0.6
    mock_settings.rag_min_similarity = 0.4
    mock_rag_service.is_available.return_value = True
    mock_rag_service.search_style_guides = AsyncMock(
        return_value=[
            {
                "content": "Low confidence result",
                "metadata": {
                    "source": "test",
                    "language": "python",
                    "document_type": "guide",
                },
                "similarity": 0.3,
            }
        ]
    )

    ctx = MagicMock()
    result = await search_style_guides(ctx, "test query", "python")

    assert result["max_similarity"] == 0.3
    assert result["confidence"] == "low"


@pytest.mark.asyncio
@patch("src.tools.rag_tools.rag_service")
async def test_search_style_guides_empty_results_confidence(mock_rag_service):
    """Test that empty results return low confidence and 0.0 max_similarity."""
    mock_rag_service.is_available.return_value = True
    mock_rag_service.search_style_guides = AsyncMock(return_value=[])

    ctx = MagicMock()
    result = await search_style_guides(ctx, "nonexistent query", "python")

    assert result["success"] is True
    assert result["max_similarity"] == 0.0
    assert result["confidence"] == "low"


@pytest.mark.asyncio
@patch("src.tools.rag_tools.settings")
@patch("src.tools.rag_tools.rag_service")
async def test_search_style_guides_confidence_boundary_high(
    mock_rag_service, mock_settings
):
    """Test confidence is high when similarity exactly equals rag_confidence_threshold."""
    mock_settings.rag_confidence_threshold = 0.6
    mock_settings.rag_min_similarity = 0.4
    mock_rag_service.is_available.return_value = True
    mock_rag_service.search_style_guides = AsyncMock(
        return_value=[
            {
                "content": "Boundary result",
                "metadata": {
                    "source": "test",
                    "language": "python",
                    "document_type": "guide",
                },
                "similarity": 0.6,  # Exactly at threshold
            }
        ]
    )

    ctx = MagicMock()
    result = await search_style_guides(ctx, "test query", "python")

    assert result["max_similarity"] == 0.6
    assert result["confidence"] == "high"


@pytest.mark.asyncio
@patch("src.tools.rag_tools.settings")
@patch("src.tools.rag_tools.rag_service")
async def test_search_style_guides_confidence_boundary_medium(
    mock_rag_service, mock_settings
):
    """Test confidence is medium when similarity exactly equals rag_min_similarity."""
    mock_settings.rag_confidence_threshold = 0.6
    mock_settings.rag_min_similarity = 0.4
    mock_rag_service.is_available.return_value = True
    mock_rag_service.search_style_guides = AsyncMock(
        return_value=[
            {
                "content": "Boundary result",
                "metadata": {
                    "source": "test",
                    "language": "python",
                    "document_type": "guide",
                },
                "similarity": 0.4,  # Exactly at min_similarity threshold
            }
        ]
    )

    ctx = MagicMock()
    result = await search_style_guides(ctx, "test query", "python")

    assert result["max_similarity"] == 0.4
    assert result["confidence"] == "medium"


@pytest.mark.asyncio
@patch("src.tools.rag_tools.settings")
@patch("src.tools.rag_tools.rag_service")
async def test_search_style_guides_max_similarity_from_multiple_results(
    mock_rag_service, mock_settings
):
    """Test that max_similarity is computed from the highest similarity among all results."""
    mock_settings.rag_confidence_threshold = 0.6
    mock_settings.rag_min_similarity = 0.4
    mock_rag_service.is_available.return_value = True
    mock_rag_service.search_style_guides = AsyncMock(
        return_value=[
            {
                "content": "Result 1",
                "metadata": {
                    "source": "test1",
                    "language": "python",
                    "document_type": "guide",
                },
                "similarity": 0.5,
            },
            {
                "content": "Result 2",
                "metadata": {
                    "source": "test2",
                    "language": "python",
                    "document_type": "guide",
                },
                "similarity": 0.75,  # Highest
            },
            {
                "content": "Result 3",
                "metadata": {
                    "source": "test3",
                    "language": "python",
                    "document_type": "guide",
                },
                "similarity": 0.6,
            },
        ]
    )

    ctx = MagicMock()
    result = await search_style_guides(ctx, "test query", "python")

    assert result["max_similarity"] == 0.75
    assert result["confidence"] == "high"
