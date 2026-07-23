"""Unit tests for codebase index backfill script."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.backfill_repo import backfill


@pytest.mark.asyncio
@patch("scripts.backfill_repo.get_github_app_auth")
@patch("scripts.backfill_repo.Github")
@patch("scripts.backfill_repo.codebase_index_service")
async def test_backfill_success(mock_index_service, mock_github, mock_get_auth) -> None:
    """Test backfill function successfully indexes repository."""
    mock_auth = AsyncMock()
    mock_auth.get_installation_access_token.return_value = "dummy-token"
    mock_get_auth.return_value = mock_auth

    mock_github_client = MagicMock()
    mock_github.return_value = mock_github_client

    mock_repo = MagicMock()
    mock_github_client.get_repo.return_value = mock_repo

    mock_index_service.is_available.return_value = True
    mock_index_result = MagicMock()
    mock_index_result.files_indexed = 10
    mock_index_result.files_skipped = []
    mock_index_service.index_full_repo = AsyncMock(return_value=mock_index_result)

    await backfill("owner/repo", "main", 0.5)

    mock_github_client.get_repo.assert_called_once_with("owner/repo")
    mock_index_service.index_full_repo.assert_called_once_with(
        mock_repo, ref="main", delay_seconds=0.5
    )


@pytest.mark.asyncio
@patch("scripts.backfill_repo.codebase_index_service")
@patch("scripts.backfill_repo.sys")
async def test_backfill_unavailable_exits(mock_sys, mock_index_service) -> None:
    """Test backfill function exits with code 1 if codebase index service is unavailable."""
    mock_index_service.is_available.return_value = False
    mock_sys.exit.side_effect = SystemExit(1)

    with pytest.raises(SystemExit) as exc_info:
        await backfill("owner/repo", "main", 0.0)

    assert exc_info.value.code == 1
    mock_sys.exit.assert_called_once_with(1)


@pytest.mark.asyncio
@patch("scripts.backfill_repo.get_github_app_auth")
@patch("scripts.backfill_repo.Github")
@patch("scripts.backfill_repo.codebase_index_service")
@patch("scripts.backfill_repo.sys")
async def test_backfill_exception_exits(
    mock_sys, mock_index_service, mock_github, mock_get_auth
) -> None:
    """Test backfill function exits with code 1 if backfill fails with exception."""
    mock_auth = AsyncMock()
    mock_auth.get_installation_access_token.return_value = "dummy-token"
    mock_get_auth.return_value = mock_auth

    mock_github_client = MagicMock()
    mock_github.return_value = mock_github_client
    mock_github_client.get_repo.side_effect = Exception("GitHub API down")

    mock_index_service.is_available.return_value = True
    mock_sys.exit.side_effect = SystemExit(1)

    with pytest.raises(SystemExit) as exc_info:
        await backfill("owner/repo", "main", 0.0)

    assert exc_info.value.code == 1
    mock_sys.exit.assert_called_once_with(1)
