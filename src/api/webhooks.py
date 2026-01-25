"""GitHub webhook router and signature validation."""

import hashlib
import hmac
import logging
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from rq import Worker
from rq.exceptions import NoSuchJobError
from rq.job import Job
from rq.registry import FailedJobRegistry, FinishedJobRegistry, StartedJobRegistry

from src.api.handlers.webhook_event_handlers import (
    handle_issue_comment_event,
    handle_ping_event,
    handle_pull_request_event,
    handle_review_comment_event,
)
from src.config.settings import settings
from src.queue.config import redis_conn, review_queue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhooks"])


# =============================================================================
# Queue Status Endpoints
# =============================================================================


@router.get("/queue/status")
async def queue_status() -> dict[str, int]:
    """Return aggregate queue metrics."""
    return {
        "queued": review_queue.count,
        "started": len(StartedJobRegistry(queue=review_queue)),
        "finished": len(FinishedJobRegistry(queue=review_queue)),
        "failed": len(FailedJobRegistry(queue=review_queue)),
        "active_workers": len(Worker.all(connection=redis_conn)),
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

    return {
        "job_id": job.id,
        "status": status_value,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
        "result": (
            getattr(latest_result, "return_value", None)
            if latest_result and status_value == "finished"
            else None
        ),
        "exc_info": (
            getattr(latest_result, "exc_string", None)
            if latest_result and status_value == "failed"
            else None
        ),
    }


# =============================================================================
# Webhook Signature Validation
# =============================================================================


async def validate_signature(
    request: Request,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
) -> None:
    """Validate GitHub webhook signature using HMAC-SHA256."""
    if not x_hub_signature_256:
        logger.warning("Missing X-Hub-Signature-256 header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Hub-Signature-256 header",
        )

    body = await request.body()

    webhook_secret = settings.github_webhook_secret
    if not webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook secret not configured",
        )

    secret = webhook_secret.encode("utf-8")
    expected_signature = f"sha256={hmac.new(secret, body, hashlib.sha256).hexdigest()}"

    if not hmac.compare_digest(expected_signature, x_hub_signature_256):
        logger.warning("Invalid webhook signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
        )


# =============================================================================
# Main Webhook Router
# =============================================================================


@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
) -> Mapping[str, str | int]:
    """Route GitHub webhook events to appropriate handlers."""
    await validate_signature(request, x_hub_signature_256)
    payload: dict[str, Any] = await request.json()

    match x_github_event:
        case "ping":
            return handle_ping_event()
        case "pull_request":
            return handle_pull_request_event(payload)
        case "pull_request_review_comment":
            return await handle_review_comment_event(payload)
        case "issue_comment":
            return handle_issue_comment_event(payload)
        case _:
            logger.info(f"Ignoring event type: {x_github_event}")
            return {"message": f"Event {x_github_event} not supported"}
