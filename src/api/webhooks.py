"""GitHub webhook handlers."""

import hashlib
import hmac
import logging
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from github import Auth, Github

from src.agents.code_reviewer import code_review_agent, validate_review_result
from src.config.settings import settings
from src.models.dependencies import ReviewDependencies
from src.services.github_auth import github_app_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhooks"])

# Track in-progress reviews to prevent duplicates
_active_reviews: set[str] = set()


async def process_pr_review(repo_name: str, pr_number: int) -> None:
    """Process PR review in the background.

    Args:
        repo_name: Repository full name (owner/repo)
        pr_number: Pull request number
    """
    review_key = f"{repo_name}#{pr_number}"

    # Check if already processing
    if review_key in _active_reviews:
        logger.warning(f"Review already in progress for {review_key}, skipping")
        return

    try:
        # Mark as active
        _active_reviews.add(review_key)
        logger.info(f"Starting background review for {review_key}")

        # Get installation access token
        installation_token = await github_app_auth.get_installation_access_token()

        # Create GitHub client with installation token using new Auth API
        auth = Auth.Token(installation_token)
        github_client = Github(auth=auth)

        # Create HTTP client for additional API calls
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            # Pre-fetch repo and PR objects
            repo = github_client.get_repo(repo_name)
            pr = repo.get_pull(pr_number)

            # Create dependencies for the agent
            deps = ReviewDependencies(
                github_client=github_client,
                http_client=http_client,
                pr_number=pr_number,
                repo_full_name=repo_name,
                repo=repo,
                pr=pr,
            )

            # Post initial "review in progress" comment
            bot_name = settings.bot_name
            progress_message = (
                f"🤖 **{bot_name}** is currently reviewing your PR...\n\n"
                f"I'll post detailed feedback shortly. Thanks for your patience!"
            )
            pr.create_issue_comment(body=progress_message)
            logger.info(f"Posted 'review in progress' comment for PR #{pr_number}")

            # Run the code review agent
            logger.info(f"Running AI code review for PR #{pr_number}")
            result = await code_review_agent.run(
                user_prompt=f"Please review pull request #{pr_number} in {repo_name}. "
                f"Analyze the changes and provide constructive feedback.",
                deps=deps,
            )

            # Validate and correct the result
            validated_result = validate_review_result(
                repo_full_name=repo_name,
                pr_number=pr_number,
                result=result.output,
            )

            logger.info(
                f"Review completed for {review_key}: "
                f"{validated_result.total_comments} comments, "
                f"recommendation: {validated_result.summary.recommendation}"
            )

    except Exception as e:
        logger.error(f"Error processing review for {review_key}: {e}", exc_info=True)
        raise

    finally:
        # Remove from active set
        _active_reviews.discard(review_key)


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
    background_tasks: BackgroundTasks,
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
            review_key = f"{repo_name}#{pr_number}"

            # Check if already processing (deduplication)
            if review_key in _active_reviews:
                logger.info(
                    f"Review already in progress for {review_key}, ignoring duplicate"
                )
                return {
                    "message": f"PR #{pr_number} review already in progress",
                    "status": "duplicate",
                }

            # Add background task to process review
            background_tasks.add_task(process_pr_review, repo_name, pr_number)

            logger.info(f"Queued background review for PR #{pr_number}")
            return {
                "message": f"PR #{pr_number} review queued",
                "status": "accepted",
            }
        else:
            logger.info(f"Ignoring PR {action} event")
            return {"message": f"Event {action} ignored"}

    # Ignore other events
    logger.info(f"Ignoring event type: {x_github_event}")
    return {"message": f"Event {x_github_event} not supported"}
