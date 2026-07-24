"""Unit tests for handle_pr_merge handler."""

from unittest.mock import patch

import pytest

from src.api.handlers.pr_merge_handler import handle_pr_merge


@pytest.mark.asyncio
@patch("src.api.handlers.pr_merge_handler.rabbitmq_service")
async def test_handle_pr_merge_success(mock_rabbitmq) -> None:
    """Test handle_pr_merge successfully publishes a reindex job."""
    mock_rabbitmq.is_available.return_value = True

    payload = {
        "pull_request": {
            "number": 42,
            "head": {"sha": "headsha123"},
        },
        "repository": {
            "full_name": "owner/repo",
        },
    }

    await handle_pr_merge(payload, installation_id=123)

    mock_rabbitmq.publish_reindex_job.assert_called_once_with(
        "owner/repo", 42, "headsha123"
    )


@pytest.mark.asyncio
@patch("src.api.handlers.pr_merge_handler.rabbitmq_service")
async def test_handle_pr_merge_missing_keys(mock_rabbitmq) -> None:
    """Test handle_pr_merge handles missing payload keys gracefully without publishing."""
    mock_rabbitmq.is_available.return_value = True

    # Missing head sha
    payload = {
        "pull_request": {
            "number": 42,
        },
        "repository": {
            "full_name": "owner/repo",
        },
    }

    await handle_pr_merge(payload, installation_id=123)

    mock_rabbitmq.publish_reindex_job.assert_not_called()


@pytest.mark.asyncio
@patch("src.api.handlers.pr_merge_handler.rabbitmq_service")
async def test_handle_pr_merge_rabbitmq_unavailable(mock_rabbitmq) -> None:
    """Test handle_pr_merge does not publish if RabbitMQ service is unavailable."""
    mock_rabbitmq.is_available.return_value = False

    payload = {
        "pull_request": {
            "number": 42,
            "head": {"sha": "headsha123"},
        },
        "repository": {
            "full_name": "owner/repo",
        },
    }

    await handle_pr_merge(payload, installation_id=123)

    mock_rabbitmq.publish_reindex_job.assert_not_called()


@pytest.mark.asyncio
@patch("src.api.handlers.pr_merge_handler.rabbitmq_service")
async def test_handle_pr_merge_publish_exception(mock_rabbitmq) -> None:
    """Test handle_pr_merge handles exceptions during publishing gracefully."""
    mock_rabbitmq.is_available.return_value = True
    mock_rabbitmq.publish_reindex_job.side_effect = Exception("Publish error")

    payload = {
        "pull_request": {
            "number": 42,
            "head": {"sha": "headsha123"},
        },
        "repository": {
            "full_name": "owner/repo",
        },
    }

    # Should not raise exception
    await handle_pr_merge(payload, installation_id=123)

    mock_rabbitmq.publish_reindex_job.assert_called_once_with(
        "owner/repo", 42, "headsha123"
    )
