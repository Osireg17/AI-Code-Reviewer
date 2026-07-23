"""Unit tests for RabbitMQ reindexing worker."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workers.reindex_worker import main, process_reindex_job


@pytest.mark.asyncio
@patch("src.workers.reindex_worker.RefreshingAppAuth")
@patch("src.workers.reindex_worker.Github")
@patch("src.workers.reindex_worker.codebase_index_service")
async def test_process_reindex_job_success(
    mock_index_service, mock_github, mock_get_auth
) -> None:
    """Test process_reindex_job successfully processes a valid message."""
    mock_auth = MagicMock()
    mock_get_auth.return_value = mock_auth
    mock_github_client = MagicMock()
    mock_github.return_value = mock_github_client

    mock_repo = MagicMock()
    mock_pr = MagicMock()
    mock_github_client.get_repo.return_value = mock_repo
    mock_repo.get_pull.return_value = mock_pr

    mock_index_service.is_available.return_value = True
    mock_index_result = MagicMock()
    mock_index_result.files_indexed = 5
    mock_index_result.files_skipped = []
    mock_index_service.index_changed_files = AsyncMock(return_value=mock_index_result)

    message = {
        "repo_full_name": "owner/repo",
        "pr_number": 42,
        "head_sha": "sha123",
    }

    await process_reindex_job(message)

    mock_github_client.get_repo.assert_called_once_with("owner/repo")
    mock_repo.get_pull.assert_called_once_with(42)
    mock_index_service.index_changed_files.assert_called_once_with(mock_repo, mock_pr)


@pytest.mark.asyncio
async def test_process_reindex_job_malformed_message() -> None:
    """Test process_reindex_job returns early on malformed message."""
    message = {"repo_full_name": "owner/repo"}  # missing pr_number and head_sha

    # Should not raise exception
    await process_reindex_job(message)


@pytest.mark.asyncio
@patch("src.workers.reindex_worker.RefreshingAppAuth")
@patch("src.workers.reindex_worker.Github")
@patch("src.workers.reindex_worker.codebase_index_service")
async def test_process_reindex_job_index_service_unavailable(
    mock_index_service, mock_github, mock_get_auth
) -> None:
    """Test process_reindex_job raises error if codebase index service is unavailable."""
    mock_auth = MagicMock()
    mock_get_auth.return_value = mock_auth
    mock_github_client = MagicMock()
    mock_github.return_value = mock_github_client

    mock_repo = MagicMock()
    mock_pr = MagicMock()
    mock_github_client.get_repo.return_value = mock_repo
    mock_repo.get_pull.return_value = mock_pr

    mock_index_service.is_available.return_value = False

    message = {
        "repo_full_name": "owner/repo",
        "pr_number": 42,
        "head_sha": "sha123",
    }

    with pytest.raises(RuntimeError, match="Codebase index service is not available"):
        await process_reindex_job(message)


@pytest.mark.asyncio
@patch("src.workers.reindex_worker.rabbitmq_service")
@patch("src.workers.reindex_worker.sys")
async def test_main_exits_if_rabbitmq_unavailable(mock_sys, mock_rabbitmq) -> None:
    """Test main function exits with code 1 if RabbitMQ service is unavailable."""
    mock_rabbitmq.is_available.return_value = False

    mock_sys.exit.side_effect = SystemExit(1)

    with pytest.raises(SystemExit) as exc_info:
        await main()

    assert exc_info.value.code == 1
    mock_sys.exit.assert_called_once_with(1)


@pytest.mark.asyncio
@patch("src.workers.reindex_worker.rabbitmq_service")
async def test_main_consume_keyboard_interrupt(mock_rabbitmq) -> None:
    """Test main function handles KeyboardInterrupt gracefully."""
    mock_rabbitmq.is_available.return_value = True
    mock_rabbitmq.consume_reindex_jobs.side_effect = KeyboardInterrupt()

    # Should exit cleanly without raising KeyboardInterrupt or sys.exit(1)
    await main()


@pytest.mark.asyncio
@patch("src.workers.reindex_worker.rabbitmq_service")
@patch("src.workers.reindex_worker.sys")
async def test_main_consume_exception_crashes(mock_sys, mock_rabbitmq) -> None:
    """Test main function exits with code 1 if consume raises unexpected exception."""
    mock_rabbitmq.is_available.return_value = True
    mock_rabbitmq.consume_reindex_jobs.side_effect = Exception("Crash")

    mock_sys.exit.side_effect = SystemExit(1)

    with pytest.raises(SystemExit) as exc_info:
        await main()

    assert exc_info.value.code == 1
    mock_sys.exit.assert_called_once_with(1)
