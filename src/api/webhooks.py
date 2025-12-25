"""GitHub webhook handlers."""

import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from redis.exceptions import ConnectionError as RedisConnectionError
from rq import Worker
from rq.exceptions import NoSuchJobError
from rq.job import Job
from rq.registry import FailedJobRegistry, FinishedJobRegistry, StartedJobRegistry

from src.config.settings import settings
from src.queue.config import enqueue_review, redis_conn, review_queue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhooks"])


@router.get("/queue/status")
async def queue_status() -> dict[str, int]:
    """Return aggregate queue metrics."""
    queued_jobs = review_queue.count
    started_registry = StartedJobRegistry(queue=review_queue)
    finished_registry = FinishedJobRegistry(queue=review_queue)
    failed_registry = FailedJobRegistry(queue=review_queue)
    active_workers = len(Worker.all(connection=redis_conn))

    return {
        "queued": queued_jobs,
        "started": len(started_registry),
        "finished": len(finished_registry),
        "failed": len(failed_registry),
        "active_workers": active_workers,
    }


@router.get("/queue/job/{job_id}")
async def queue_job(job_id: str) -> dict[str, Any]:
    """Return details for a specific queued job."""
    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except NoSuchJobError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        ) from err

    status_value = job.get_status(refresh=True)
    latest_result = job.latest_result()
    latest_return = (
        getattr(latest_result, "return_value", None) if latest_result else None
    )
    latest_traceback = (
        getattr(latest_result, "exc_string", None) if latest_result else None
    )
    return {
        "job_id": job.id,
        "status": status_value,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
        "result": latest_return if status_value == "finished" else None,
        "exc_info": latest_traceback if status_value == "failed" else None,
    }


# ====================
# This function stays in webhooks.py (shared across all webhook handlers)
async def validate_signature(
    request: Request,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
) -> None:
    """
    Validate GitHub webhook signature.

    Args:
        request: The incoming request
        x_hub_signature_256: GitHub signature from header

    Raises:
        HTTPException: If signature is missing or invalid
    """
    if not x_hub_signature_256:
        logger.warning("Missing X-Hub-Signature-256 header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Hub-Signature-256 header",
        )

    # Read the request body
    body = await request.body()

    # Compute the expected signature
    webhook_secret = settings.github_webhook_secret
    if not webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook secret not configured",
        )
    secret = webhook_secret.encode("utf-8")
    expected_signature = f"sha256={hmac.new(secret, body, hashlib.sha256).hexdigest()}"

    # Compare signatures securely
    if not hmac.compare_digest(expected_signature, x_hub_signature_256):
        logger.warning("Invalid webhook signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
        )


@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
) -> dict[str, str | int]:
    """
    Handle GitHub webhook events.

    Args:
        request: The incoming request
        x_github_event: The type of GitHub event
        x_hub_signature_256: GitHub signature for verification

    Returns:
        Success message

    Raises:
        HTTPException: If validation fails or event processing fails
    """
    # Validate the webhook signature
    await validate_signature(request, x_hub_signature_256)

    # Parse the payload
    payload: dict[str, Any] = await request.json()

    # Handle ping event
    if x_github_event == "ping":
        logger.info("Received ping event from GitHub")
        return {"message": "pong"}

    # Handle pull request events
    if x_github_event == "pull_request":
        action = payload.get("action")
        pr_number = payload.get("pull_request", {}).get("number")
        repo_name = payload.get("repository", {}).get("full_name")
        pr_state = payload.get("pull_request", {}).get("state")

        logger.info(
            f"Received PR {action} event for PR #{pr_number} in {repo_name} (state: {pr_state})"
        )

        # Handle closed/merged PRs - nothing to queue
        if action == "closed":
            return {
                "message": f"PR #{pr_number} closed, cleaned up",
                "status": "closed",
            }

        # Skip if PR is already closed/merged
        if pr_state != "open":
            logger.info(f"Skipping review for PR #{pr_number} - PR is {pr_state}")
            return {
                "message": f"PR #{pr_number} is {pr_state}, skipping review",
                "status": "skipped",
            }

        # Only process opened and reopened events
        if action in ["opened", "reopened"]:
            labels = payload.get("pull_request", {}).get("labels", []) or []
            label_names = [label.get("name", "").lower() for label in labels]
            changed_files = payload.get("pull_request", {}).get("changed_files")

            priority: str | None
            if any(
                keyword in name
                for name in label_names
                for keyword in ("critical", "security")
            ):
                priority = "high"
            elif isinstance(changed_files, int) and changed_files > 20:
                priority = "low"
            else:
                priority = "default"

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

            logger.info(
                f"Queued background review for PR #{pr_number} (action: {action})"
            )
            return {
                "message": f"PR #{pr_number} review queued",
                "status": "accepted",
                "job_id": job.id,
            }
        else:
            logger.info(f"Ignoring PR {action} event")
            return {"message": f"Event {action} ignored"}

    # ====================
    # CONVERSATION HANDLER (Phase 2)
    # ====================
    # Handle user replies to bot comments
    if x_github_event == "pull_request_review_comment":
        """Handle user replies to bot comments."""
        action = payload.get("action")
        comment = payload.get("comment", {})

        logger.info(f"Received review comment {action} event")

        # Only process created comments that are replies
        if action == "created" and comment.get("in_reply_to_id") is not None:
            user_login = comment.get("user", {}).get("login", "")
            bot_login = settings.github_app_bot_login or ""
            # TODO: UNCOMMENT when implementing conversation feature
            # from src.api.handlers.conversation_handler import handle_conversation_reply
            # result = await handle_conversation_reply(payload)
            # return result
            if user_login == bot_login:
                logger.info("Ignoring bot's own reply to a comment")
                return {"message": "Bot reply ignored", "status": "ignored"}
            logger.info(
                "User replied to a comment (conversation handler not implemented yet)"
            )
            return {"message": "Conversation feature coming soon", "status": "ignored"}

        logger.info(f"Ignoring review comment {action} event (not a reply)")
        return {"message": f"Review comment {action} ignored"}

    # Ignore other events
    logger.info(f"Ignoring event type: {x_github_event}")
    return {"message": f"Event {x_github_event} not supported"}
