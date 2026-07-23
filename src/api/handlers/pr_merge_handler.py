"""Handler for pull request merge events."""

import logging
from typing import Any

from src.services.rabbitmq_service import rabbitmq_service

logger = logging.getLogger(__name__)


async def handle_pr_merge(payload: dict[str, Any], installation_id: int | None) -> None:
    """Handle pull_request merged event and publish reindex job to RabbitMQ.

    Args:
        payload: The GitHub webhook payload
        installation_id: The GitHub App installation ID
    """
    pr_data = payload.get("pull_request", {})
    pr_number = pr_data.get("number")
    repo_name = payload.get("repository", {}).get("full_name")
    head_sha = pr_data.get("head", {}).get("sha")

    if not pr_number or not repo_name or not head_sha:
        logger.warning(
            "PR merge payload missing key info: repo=%s, pr=%s, sha=%s",
            repo_name,
            pr_number,
            head_sha,
        )
        return

    logger.info(
        "Handling merged PR #%s for %s (installation_id: %s)",
        pr_number,
        repo_name,
        installation_id,
    )
    if rabbitmq_service.is_available():
        try:
            await rabbitmq_service.publish_reindex_job(
                repo_name, pr_number, head_sha, installation_id
            )
        except Exception as e:
            logger.error(
                "Failed to publish reindex job for %s PR #%s: %s",
                repo_name,
                pr_number,
                e,
            )
    else:
        logger.warning("RabbitMQ service unavailable - cannot publish reindex job")
