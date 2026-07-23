"""Worker entrypoint for processing RabbitMQ codebase reindexing jobs."""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from github import Github

from src.services.codebase_index_service import codebase_index_service
from src.services.github_auth import RefreshingAppAuth
from src.services.rabbitmq_service import rabbitmq_service
from src.utils.logging import setup_observability

logger = logging.getLogger(__name__)


async def process_reindex_job(message: dict[str, Any]) -> None:
    """Callback to process RabbitMQ codebase reindexing tasks.

    Args:
        message: The job message body containing repository metadata
    """
    repo_full_name = message.get("repo_full_name")
    pr_number = message.get("pr_number")
    head_sha = message.get("head_sha")
    installation_id = message.get("installation_id")

    if not repo_full_name or not pr_number or not head_sha:
        logger.error("Malformed reindex message received: %s", message)
        return

    logger.info(
        "Starting codebase reindexing for %s PR #%s (SHA: %s, Installation: %s)",
        repo_full_name,
        pr_number,
        head_sha,
        installation_id,
    )

    try:
        auth = RefreshingAppAuth(installation_id=installation_id)
        github_client = Github(auth=auth)

        repo = github_client.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)

        if codebase_index_service.is_available():
            result = await codebase_index_service.index_changed_files(repo, pr)
            logger.info(
                "Successfully reindexed %s PR #%s (indexed %d files, skipped %d files)",
                repo_full_name,
                pr_number,
                result.files_indexed,
                len(result.files_skipped),
            )
        else:
            raise RuntimeError("Codebase index service is not available")
    except Exception as e:
        logger.error(
            "Failed to complete reindexing for %s PR #%s: %s",
            repo_full_name,
            pr_number,
            e,
        )
        raise


async def main() -> None:
    """Start the RabbitMQ reindexing worker."""
    setup_observability()

    logger.info("Initializing reindexing worker...")

    if not rabbitmq_service.is_available():
        logger.error("RabbitMQ service is not available. Exiting worker.")
        sys.exit(1)

    try:
        await rabbitmq_service.consume_reindex_jobs(process_reindex_job)
    except KeyboardInterrupt:
        logger.info("Reindexing worker stopped by keyboard interrupt.")
    except Exception as e:
        logger.critical("Reindexing worker crashed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
