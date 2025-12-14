"""GitHub webhook handlers."""

import hashlib
import hmac
import logging
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from github import Auth, Github
from github.PullRequest import PullRequest
from sqlalchemy.orm import Session

from src.agents.code_reviewer import code_review_agent, validate_review_result
from src.config.settings import settings
from src.database.db import SessionLocal
from src.models.dependencies import ReviewDependencies
from src.models.outputs import CodeReviewResult
from src.models.review_state import ReviewState
from src.services.github_auth import github_app_auth
from src.utils.rate_limiter import with_exponential_backoff

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhooks"])

# Track in-progress reviews to prevent duplicates
_active_reviews: set[str] = set()


async def process_pr_review(
    repo_name: str,
    pr_number: int,
    action: str = "opened",
    session_factory: Callable[[], Session] | None = None,
    github_auth: Any = None,  # GitHubAppAuth | None (using Any to avoid type errors with proxy)
    agent: Any = None,
    active_reviews: set[str] | None = None,
) -> None:
    """Process PR review in the background.

    Args:
        repo_name: Repository full name (owner/repo)
        pr_number: Pull request number
        action: PR event action (opened, reopened, synchronize)
        session_factory: Database session factory (default: SessionLocal)
        github_auth: GitHub App authentication service (default: github_app_auth)
        agent: Code review agent (default: code_review_agent)
        active_reviews: Set of active review keys for deduplication (default: _active_reviews)
    """
    # Apply defaults for dependency injection
    if active_reviews is None:
        active_reviews = _active_reviews
    if session_factory is None:
        session_factory = SessionLocal
    if github_auth is None:
        github_auth = github_app_auth
    if agent is None:
        agent = code_review_agent

    review_key = f"{repo_name}#{pr_number}"

    if review_key in active_reviews:
        logger.warning(f"Review already in progress for {review_key}, skipping")
        return

    db = session_factory()
    active_reviews.add(review_key)
    try:
        logger.info(f"Starting background review for {review_key}")
        installation_token = await github_auth.get_installation_access_token()
        auth = Auth.Token(installation_token)
        github_client = Github(auth=auth)

        async with httpx.AsyncClient(timeout=30.0) as http_client:
            repo = github_client.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            (
                is_incremental,
                base_commit_sha,
                review_state,
            ) = await _determine_review_type(db, repo_name, pr_number, pr, action)
            deps = ReviewDependencies(
                github_client=github_client,
                http_client=http_client,
                pr_number=pr_number,
                repo_full_name=repo_name,
                repo=repo,
                pr=pr,
                db_session=db,
                is_incremental_review=is_incremental,
                base_commit_sha=base_commit_sha,
            )
            await _post_progress_comment_if_needed(pr, action)
            validated_result = await _run_code_review_agent(
                repo_name, pr_number, deps, agent
            )
            await _post_inline_comments_if_needed(pr, validated_result, deps)
            await _post_summary_review_if_needed(
                pr, validated_result, deps, is_incremental
            )
            await _update_review_state(
                db, repo_name, pr_number, pr, is_incremental, review_key
            )
            logger.info(
                f"Review completed for {review_key}: "
                f"{validated_result.total_comments} comments, "
                f"recommendation: {validated_result.summary.recommendation}"
            )
    finally:
        active_reviews.discard(review_key)
        db.close()


async def _determine_review_type(
    db: Session,
    repo_name: str,
    pr_number: int,
    pr: PullRequest,
    action: str,
) -> tuple[bool, str | None, ReviewState | None]:
    is_incremental = action == "synchronize"
    base_commit_sha: str | None = None
    review_state: ReviewState | None = None
    if is_incremental:
        review_state = (
            db.query(ReviewState)
            .filter(
                ReviewState.repo_full_name == repo_name,
                ReviewState.pr_number == pr_number,
            )
            .first()
        )
        if review_state and review_state.initial_review_completed:
            base_commit_sha = review_state.last_reviewed_commit_sha
            logger.info(
                f"Incremental review: comparing {base_commit_sha[:7]}..{pr.head.sha[:7]}"
            )
        else:
            is_incremental = False
            logger.info("First review for this PR - performing full review")
    return is_incremental, base_commit_sha, review_state


async def _post_progress_comment_if_needed(pr: PullRequest, action: str) -> None:
    if action in {"opened", "reopened"}:
        bot_name = settings.bot_name
        progress_message = (
            f"🤖 **{bot_name}** is currently reviewing your PR...\n\n"
            f"I'll post detailed feedback shortly. Thanks for your patience!"
        )
        pr.create_issue_comment(body=progress_message)
        logger.info(f"Posted 'review in progress' comment for PR #{pr.number}")
    else:
        logger.debug(f"Skipping progress comment for '{action}' event")


async def _run_code_review_agent(
    repo_name: str, pr_number: int, deps: ReviewDependencies, agent: Any
) -> CodeReviewResult:
    """Run the code review agent with the given dependencies.

    Args:
        repo_name: Repository full name
        pr_number: Pull request number
        deps: Review dependencies
        agent: Code review agent instance

    Returns:
        Validated code review result
    """
    logger.info(f"Running AI code review for PR #{pr_number}")
    result: Any = await with_exponential_backoff(
        agent.run,
        user_prompt=f"Please review pull request #{pr_number} in {repo_name}. "
        f"Analyze the changes and provide constructive feedback.",
        deps=deps,
    )
    return validate_review_result(
        repo_full_name=repo_name,
        pr_number=pr_number,
        result=result.output,
    )


async def _post_inline_comments_if_needed(
    pr: PullRequest, validated_result: CodeReviewResult, deps: ReviewDependencies
) -> None:
    if deps._cache.get("inline_comments_posted", False):  # noqa: F841
        logger.info(
            "Inline comments already posted by agent; skipping webhook inline posts"
        )
        return
    logger.info(f"Posting {len(validated_result.comments)} inline comments")
    files_cache = {file.filename: file.patch for file in pr.get_files()}
    posted_count = 0
    skipped_count = 0
    from src.tools.github_tools import _is_line_in_diff

    for comment in validated_result.comments:
        file_patch = files_cache.get(comment.file_path)
        if not file_patch:
            logger.warning(
                f"Skipping comment on {comment.file_path}:{comment.line_number} - file not found in PR"
            )
            skipped_count += 1
            continue
        if not _is_line_in_diff(file_patch, comment.line_number):
            logger.warning(
                f"Skipping comment on {comment.file_path}:{comment.line_number} - line not in diff"
            )
            skipped_count += 1
            continue
        pr.create_review_comment(
            body=comment.comment_body,
            commit=pr.head.sha,
            path=comment.file_path,
            line=comment.line_number,
        )
        logger.debug(f"Posted comment on {comment.file_path}:{comment.line_number}")
        posted_count += 1
    logger.info(f"Posted {posted_count} comments, skipped {skipped_count}")


async def _post_summary_review_if_needed(
    pr: PullRequest,
    validated_result: CodeReviewResult,
    deps: ReviewDependencies,
    is_incremental: bool,
) -> None:
    if is_incremental:
        logger.info(
            "Skipping summary comment for incremental review (synchronize event)"
        )
        return
    summary_text = validated_result.format_summary_markdown()
    approval_status_map = {
        "APPROVE": "APPROVE",
        "REQUEST_CHANGES": "REQUEST_CHANGES",
        "COMMENT": "COMMENT",
    }
    approval_status = approval_status_map.get(
        validated_result.summary.recommendation, "COMMENT"
    )
    if deps._cache.get("summary_review_posted", False):
        logger.info(
            "Summary review already posted by agent; skipping webhook summary post"
        )
    else:
        pr.create_review(body=summary_text, event=approval_status)
        logger.info(f"Posted summary review with status: {approval_status}")


async def _update_review_state(
    db: Session,
    repo_name: str,
    pr_number: int,
    pr: PullRequest,
    is_incremental: bool,
    review_key: str,
) -> None:
    if review_state := (
        db.query(ReviewState)
        .filter(
            ReviewState.repo_full_name == repo_name,
            ReviewState.pr_number == pr_number,
        )
        .first()
    ):
        review_state.update_review_state(
            new_commit_sha=pr.head.sha,
            mark_initial_complete=not is_incremental,
        )
        logger.info(f"Updated ReviewState for {review_key}: {pr.head.sha[:7]}")
    else:
        review_state = ReviewState(
            repo_full_name=repo_name,
            pr_number=pr_number,
            last_reviewed_commit_sha=pr.head.sha,
            initial_review_completed=True,
        )
        db.add(review_state)
        logger.info(f"Created ReviewState for {review_key}: {pr.head.sha[:7]}")
    db.commit()


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
        pr_state = payload.get("pull_request", {}).get("state")

        logger.info(
            f"Received PR {action} event for PR #{pr_number} in {repo_name} (state: {pr_state})"
        )

        # Handle closed/merged PRs - clean up active reviews
        if action == "closed":
            review_key = f"{repo_name}#{pr_number}"
            if review_key in _active_reviews:
                _active_reviews.discard(review_key)
                logger.info(f"Removed {review_key} from active reviews (PR closed)")
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

            # Add background task to process review (pass action to control progress comment)
            background_tasks.add_task(process_pr_review, repo_name, pr_number, action)

            logger.info(
                f"Queued background review for PR #{pr_number} (action: {action})"
            )
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
