"""GitHub webhook handlers."""

import hashlib
import hmac
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, status
from github import Github

from src.agents.code_reviewer import code_review_agent, validate_review_result
from src.config.settings import settings
from src.models.dependencies import ReviewDependencies
from src.services.github_auth import github_app_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhooks"])


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
    expected_signature = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

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

        logger.info(f"Received PR {action} event for PR #{pr_number} in {repo_name}")

        # Only process opened, reopened, and synchronize events
        if action in ["opened", "reopened", "synchronize"]:
            logger.info(f"Processing PR #{pr_number} for review")

            try:
                # Get installation access token
                installation_token = (
                    await github_app_auth.get_installation_access_token()
                )

                # Create GitHub client with installation token
                github_client = Github(installation_token)

                # Create HTTP client for additional API calls if needed
                async with httpx.AsyncClient() as http_client:
                    # Create dependencies for the agent
                    deps = ReviewDependencies(
                        github_client=github_client,
                        http_client=http_client,
                        pr_number=pr_number,
                        repo_full_name=repo_name,
                    )

                    # Run the code review agent
                    logger.info(f"Starting AI code review for PR #{pr_number}")
                    result = await code_review_agent.run(
                        user_prompt=f"Please review pull request #{pr_number} in {repo_name}. "
                        f"Analyze the changes and provide constructive feedback.",
                        deps=deps,
                    )

                    # Validate and correct the result
                    # Note: Pydantic AI returns the result directly, not in a .data attribute
                    validated_result = validate_review_result(
                        repo_full_name=repo_name,
                        pr_number=pr_number,
                        result=result.output,
                    )

                    logger.info(
                        f"Review completed for PR #{pr_number}: "
                        f"{validated_result.total_comments} comments, "
                        f"recommendation: {validated_result.summary.recommendation}"
                    )

                    return {
                        "message": f"PR #{pr_number} reviewed successfully",
                        "status": "completed",
                        "comments_posted": validated_result.total_comments,
                        "recommendation": validated_result.summary.recommendation,
                    }

            except Exception as e:
                logger.error(f"Error processing PR #{pr_number}: {e}", exc_info=True)
                return {
                    "message": f"Error reviewing PR #{pr_number}",
                    "status": "error",
                    "error": str(e),
                }
        else:
            logger.info(f"Ignoring PR {action} event")
            return {"message": f"Event {action} ignored"}

    # Ignore other events
    logger.info(f"Ignoring event type: {x_github_event}")
    return {"message": f"Event {x_github_event} not supported"}
