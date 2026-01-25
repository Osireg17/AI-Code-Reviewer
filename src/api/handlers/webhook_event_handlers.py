"""Handlers for specific GitHub webhook event types."""

import logging
from typing import Any

from fastapi import HTTPException, status
from redis.exceptions import ConnectionError as RedisConnectionError

from src.api.handlers.conversation_handler import handle_conversation_reply
from src.config.settings import settings
from src.queue.config import enqueue_review

logger = logging.getLogger(__name__)


# =============================================================================
# Ping Event
# =============================================================================


def handle_ping_event() -> dict[str, str]:
    """Handle GitHub ping event (webhook setup verification)."""
    logger.info("Received ping event from GitHub")
    return {"message": "pong"}


# =============================================================================
# Pull Request Events
# =============================================================================


def handle_pull_request_event(payload: dict[str, Any]) -> dict[str, str | int]:
    """Handle pull_request events (opened, reopened, synchronize, closed)."""
    action = payload.get("action")
    pr_data = payload.get("pull_request", {})
    pr_number = pr_data.get("number")
    repo_name = payload.get("repository", {}).get("full_name")
    pr_state = pr_data.get("state")

    logger.info(
        f"Received PR {action} event for PR #{pr_number} in {repo_name} (state: {pr_state})"
    )

    if action == "closed":
        return {"message": f"PR #{pr_number} closed, cleaned up", "status": "closed"}

    if pr_state != "open":
        logger.info(f"Skipping review for PR #{pr_number} - PR is {pr_state}")
        return {
            "message": f"PR #{pr_number} is {pr_state}, skipping review",
            "status": "skipped",
        }

    if action in ["opened", "reopened", "synchronize"]:
        return _enqueue_pr_review(payload, pr_number, repo_name, action)

    logger.info(f"Ignoring PR {action} event")
    return {"message": f"Event {action} ignored"}


def _enqueue_pr_review(
    payload: dict[str, Any],
    pr_number: int,
    repo_name: str,
    action: str,
) -> dict[str, str | int]:
    """Determine priority and enqueue a PR review job."""
    pr_data = payload.get("pull_request", {})
    labels = pr_data.get("labels", []) or []
    label_names = [label.get("name", "").lower() for label in labels]
    changed_files = pr_data.get("changed_files")

    priority = _determine_priority(label_names, changed_files)

    try:
        job = enqueue_review(repo_name, pr_number, action, priority=priority)
    except RedisConnectionError as exc:
        logger.exception(
            "Redis unavailable while enqueuing review job for %s#%s (action=%s)",
            repo_name,
            pr_number,
            action,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Queue backend unavailable",
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception(
            "Failed to enqueue review job for %s#%s (action=%s)",
            repo_name,
            pr_number,
            action,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enqueue review job: {exc}",
        ) from exc

    logger.info(f"Queued background review for PR #{pr_number} (action: {action})")
    return {
        "message": f"PR #{pr_number} review queued",
        "status": "accepted",
        "job_id": job.id,
    }


def _determine_priority(label_names: list[str], changed_files: int | None) -> str:
    """Determine job priority based on PR labels and size."""
    if any(
        keyword in name for name in label_names for keyword in ("critical", "security")
    ):
        return "high"
    if isinstance(changed_files, int) and changed_files > 20:
        return "low"
    return "default"


# =============================================================================
# Review Comment Events
# =============================================================================


async def handle_review_comment_event(
    payload: dict[str, Any],
) -> dict[str, str | int]:
    """Handle pull_request_review_comment events (conversation replies)."""
    action = payload.get("action")
    comment = payload.get("comment", {})

    logger.info(f"Received review comment {action} event")

    if action == "created" and comment.get("in_reply_to_id") is not None:
        result: dict[str, Any] = await handle_conversation_reply(payload)
        return result

    logger.info(f"Ignoring review comment {action} event (not a reply)")
    return {"message": f"Review comment {action} ignored"}


# =============================================================================
# Issue Comment Events (Re-review Triggers)
# =============================================================================


def handle_issue_comment_event(payload: dict[str, Any]) -> dict[str, str | int]:
    """Handle issue_comment events (re-review triggers on PR comments)."""
    action = payload.get("action")
    comment = payload.get("comment", {})
    issue = payload.get("issue", {})
    repository = payload.get("repository", {})

    if "pull_request" not in issue:
        logger.info("Ignoring issue comment (not a PR)")
        return {"message": "Issue comment ignored (not a PR)"}

    if action != "created":
        logger.info(f"Ignoring issue comment {action} event")
        return {"message": f"Issue comment {action} ignored"}

    comment_user = comment.get("user", {})
    user_login = comment_user.get("login", "")
    user_type = comment_user.get("type", "")

    if user_login == settings.github_app_bot_login or user_type == "Bot":
        logger.info(f"Ignoring bot's own comment (user={user_login})")
        return {"message": "Bot self-comment ignored"}

    return _check_re_review_trigger(comment, issue, repository, user_login)


def _check_re_review_trigger(
    comment: dict[str, Any],
    issue: dict[str, Any],
    repository: dict[str, Any],
    user_login: str,
) -> dict[str, str | int]:
    """Check if comment contains a re-review trigger and queue if so."""
    comment_body = comment.get("body", "").lower().strip()
    trigger_phrases = [phrase.lower() for phrase in settings.review_trigger_phrases]

    if all(phrase not in comment_body for phrase in trigger_phrases):
        logger.debug(f"Comment does not contain trigger phrase: {comment_body[:50]}")
        return {"message": "No trigger phrase found"}

    pr_number: int = issue.get("number", 0)
    repo_name: str = repository.get("full_name", "")

    if not pr_number or not repo_name:
        logger.warning("Missing PR number or repo name in issue comment payload")
        return {"message": "Invalid payload", "status": "error"}

    logger.info(
        f"Re-review triggered for PR #{pr_number} in {repo_name} by {user_login}"
    )

    job = enqueue_review(
        repo_name,
        pr_number,
        action="re-review",
        priority="high",
        force_full_review=True,
    )

    logger.info(f"Queued full re-review for PR #{pr_number}")
    return {
        "message": f"PR #{pr_number} full re-review queued",
        "status": "accepted",
        "job_id": job.id,
    }
