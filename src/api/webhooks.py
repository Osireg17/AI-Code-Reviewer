"""GitHub webhook handlers."""

# TODO: REFACTORING STEP 1 - UPDATE IMPORTS
# ====================
# After implementing pr_review_handler.py, update these imports:
#
# DELETE these imports (moved to pr_review_handler.py):
# - from src.agents.code_reviewer import code_review_agent, validate_review_result
# - from src.models.dependencies import ReviewDependencies
# - from src.models.outputs import CodeReviewResult
# - from src.models.review_state import ReviewState
# - from src.utils.rate_limiter import with_exponential_backoff
# - from sqlalchemy.orm import Session
# - import httpx
# - from github import Auth, Github
# - from github.PullRequest import PullRequest
# - from src.database.db import SessionLocal
# - from src.services.github_auth import github_app_auth
#
# ADD this import:
# - from src.api.handlers.pr_review_handler import handle_pr_review
#
# KEEP these imports (still needed in this file):
# - import hashlib, hmac, logging, from collections.abc import Callable, from typing import Any
# - from fastapi import APIRouter, Header, HTTPException, Request, status
# - from redis.exceptions import ConnectionError as RedisConnectionError
# - from rq import Worker, from rq.exceptions import NoSuchJobError
# - from rq.job import Job
# - from rq.registry import FailedJobRegistry, FinishedJobRegistry, StartedJobRegistry
# - from src.config.settings import settings
# - from src.queue.config import enqueue_review, redis_conn, review_queue

import hashlib
import hmac
import logging
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, status
from github import Auth, Github
from github.PullRequest import PullRequest
from redis.exceptions import ConnectionError as RedisConnectionError
from rq import Worker
from rq.exceptions import NoSuchJobError
from rq.job import Job
from rq.registry import FailedJobRegistry, FinishedJobRegistry, StartedJobRegistry
from sqlalchemy.orm import Session

from src.agents.code_reviewer import code_review_agent, validate_review_result
from src.config.settings import settings
from src.database.db import SessionLocal
from src.models.dependencies import ReviewDependencies
from src.models.outputs import CodeReviewResult
from src.models.review_state import ReviewState
from src.queue.config import enqueue_review, redis_conn, review_queue
from src.services.github_auth import github_app_auth
from src.utils.rate_limiter import with_exponential_backoff

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


# TODO: REFACTORING STEP 2 - DELETE THESE FUNCTIONS
# ====================
# After implementing pr_review_handler.py, DELETE the following functions from this file:
# 1. process_pr_review (lines ~81-154) → moved to handle_pr_review in pr_review_handler.py
# 2. _determine_review_type (lines ~157-184) → moved to pr_review_handler.py
# 3. _post_progress_comment_if_needed (lines ~187-198) → moved to pr_review_handler.py
# 4. _run_code_review_agent (lines ~200-226) → moved to pr_review_handler.py
# 5. _post_inline_comments_if_needed (lines ~228-265) → moved to pr_review_handler.py
# 6. _post_summary_review_if_needed (lines ~267-294) → moved to pr_review_handler.py
# 7. _update_review_state (lines ~296-327) → moved to pr_review_handler.py
#
# KEEP these functions:
# - validate_signature (shared across all webhook handlers)
# - github_webhook (main router - we'll update it later for conversation handler)


async def process_pr_review(
    repo_name: str,
    pr_number: int,
    action: str = "opened",
    session_factory: Callable[[], Session] | None = None,
    github_auth: Any = None,  # GitHubAppAuth | None (using Any to avoid type errors with proxy)
    agent: Any = None,
) -> None:
    """Process a PR review job (executed by queue workers).

    Args:
        repo_name: Repository full name (owner/repo)
        pr_number: Pull request number
        action: PR event action (opened, reopened, synchronize)
        session_factory: Database session factory (default: SessionLocal)
        github_auth: GitHub App authentication service (default: github_app_auth)
        agent: Code review agent (default: code_review_agent)
            Queue layer performs deduplication via deterministic job_id.
    """
    # Apply defaults for dependency injection
    if session_factory is None:
        session_factory = SessionLocal
    if github_auth is None:
        github_auth = github_app_auth
    if agent is None:
        agent = code_review_agent

    review_key = f"{repo_name}#{pr_number}"

    db = session_factory()
    logger.info("Starting review job for %s (action=%s)", review_key, action)
    try:
        installation_token = await github_auth.get_installation_access_token()
        auth = Auth.Token(installation_token)
        github_client = Github(auth=auth)
        repo = github_client.get_repo(repo_name)
        pr = repo.get_pull(pr_number)

        async with httpx.AsyncClient(timeout=30.0) as http_client:
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
        db.close()
        logger.info("Finished review job for %s", review_key)


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


# TODO: REFACTORING STEP 3 - KEEP THIS FUNCTION
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

        # Only process opened, reopened, and synchronize events
        if action in ["opened", "reopened", "synchronize"]:
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

    # TODO: REFACTORING STEP 4 - ADD CONVERSATION HANDLER (FUTURE)
    # ====================
    # After refactoring is complete, add conversation handler here:
    #
    # if x_github_event == "pull_request_review_comment":
    #     """Handle user replies to bot comments."""
    #     action = payload.get("action")
    #     comment = payload.get("comment", {})
    #
    #     logger.info(f"Received review comment {action} event")
    #
    #     # Only process created comments that are replies
    #     if action == "created":
    #         # Check if this is a reply to another comment
    #         if comment.get("in_reply_to_id"):
    #             # TODO: Import conversation handler when ready
    #             # from src.api.handlers.conversation_handler import handle_conversation_reply
    #             # return await handle_conversation_reply(payload)
    #             logger.info("User replied to a comment (conversation handler not implemented yet)")
    #             return {"message": "Conversation feature coming soon", "status": "ignored"}
    #
    #     logger.info(f"Ignoring review comment {action} event (not a reply)")
    #     return {"message": f"Review comment {action} ignored"}

    # Ignore other events
    logger.info(f"Ignoring event type: {x_github_event}")
    return {"message": f"Event {x_github_event} not supported"}
