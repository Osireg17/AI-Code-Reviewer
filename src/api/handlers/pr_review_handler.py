"""Pull request review event handler.

This module handles pull_request webhook events (opened, reopened, synchronize).

REFACTORING GUIDE:
------------------
Extract the following functions from src/api/webhooks.py:
- process_pr_review → rename to handle_pr_review
- _determine_review_type
- _post_progress_comment_if_needed
- _run_code_review_agent
- _post_inline_comments_if_needed
- _post_summary_review_if_needed
- _update_review_state

Keep validate_signature in webhooks.py (shared across all handlers).
"""

import logging
from collections.abc import Callable
from typing import Any

import httpx
from github import Auth, Github
from github.PullRequest import PullRequest
from pydantic_ai import Agent
from sqlalchemy.orm import Session

from src.agents.code_reviewer import code_review_agent, validate_review_result
from src.config.settings import settings
from src.database.db import SessionLocal
from src.models.dependencies import ReviewDependencies
from src.models.outputs import CodeReviewResult
from src.models.review_state import ReviewState
from src.services.github_auth import GitHubAppAuth
from src.utils.rate_limiter import with_exponential_backoff

logger = logging.getLogger(__name__)


# === MAIN HANDLER ===


async def handle_pr_review(
    repo_name: str,
    pr_number: int,
    action: str = "opened",
    session_factory: Callable[[], Session] | None = None,
    github_auth: GitHubAppAuth | None = None,
    agent: Agent[ReviewDependencies, Any] | None = None,
) -> None:
    """
    Process a PR review job (executed by queue workers).

    === CONTEXT ===
    Purpose: Orchestrate full PR review workflow
    Reference: src/api/webhooks.py:81-154 (process_pr_review function)

    === DEPENDENCIES ===
    - Database session factory (for ReviewState persistence)
    - GitHub App auth service (for API access tokens)
    - Code review agent (for AI analysis)

    === DATA / STATE ===
    - Database session: Per-review lifecycle, closed in finally block
    - GitHub API objects: Created per review, not persisted
    - Review dependencies (ReviewDependencies): Request-scoped cache

    === BEHAVIOR ===

    Input:
        repo_name: "owner/repo" format
        pr_number: Pull request number
        action: "opened", "reopened", or "synchronize"
        session_factory: Optional DB session factory (default: SessionLocal)
        github_auth: Optional auth service (default: github_app_auth)
        agent: Optional review agent (default: code_review_agent)

    Output:
        None (side effects: posts comments to GitHub, updates database)

    Preconditions:
        - GitHub App has valid installation token
        - Database is accessible
        - PR exists and is open

    Postconditions:
        - Review comments posted to PR
        - ReviewState updated in database
        - Database session closed

    Logic Flow:

    APPLY defaults for dependency injection
        IF session_factory is None THEN SET session_factory = SessionLocal
        IF github_auth is None THEN SET github_auth = github_app_auth
        IF agent is None THEN SET agent = code_review_agent

    INITIALIZE review_key = "{repo_name}#{pr_number}"
    INITIALIZE db = session_factory()
    LOG "Starting review job for {review_key} (action={action})"

    TRY:
        OBTAIN installation_token FROM github_auth.get_installation_access_token()
        CREATE GitHub client with token
        FETCH repository object
        FETCH pull request object

        CREATE async HTTP client (timeout=30s)
            DETERMINE review type (full vs incremental)
                CALL _determine_review_type()
                RETURNS (is_incremental, base_commit_sha, review_state)

            BUILD ReviewDependencies object
                INCLUDE github_client, http_client, pr_number, repo_full_name
                INCLUDE repo, pr, db_session
                INCLUDE is_incremental_review, base_commit_sha

            POST progress comment IF needed
                CALL _post_progress_comment_if_needed()

            RUN code review agent
                CALL _run_code_review_agent()
                RETURNS validated_result (CodeReviewResult)

            POST inline comments IF needed
                CALL _post_inline_comments_if_needed()

            POST summary review IF needed
                CALL _post_summary_review_if_needed()

            UPDATE review state in database
                CALL _update_review_state()

            LOG "Review completed for {review_key}: {comment_count} comments, recommendation: {recommendation}"

    FINALLY:
        CLOSE database session
        LOG "Finished review job for {review_key}"

    Edge Cases:
        - Database connection fails: Session closes in finally block
        - GitHub API rate limit: Handled by with_exponential_backoff
        - PR closed during review: GitHub API will error, caught by caller (queue)
        - Agent crashes: Exception propagates to queue for retry
    """

    # Apply defaults for dependency injection
    if session_factory is None:
        session_factory = SessionLocal
    if github_auth is None:
        from src.services.github_auth import get_github_app_auth

        github_auth = get_github_app_auth()
    if agent is None:
        agent = code_review_agent

    review_key = f"{repo_name}#{pr_number}"
    db = session_factory()
    logger.info(f"Starting review job for {review_key} (action={action})")

    try:
        installation_token = await github_auth.get_installation_access_token()
        gh_auth = Auth.Token(installation_token)
        github_client = Github(auth=gh_auth, per_page=100)

        repo = github_client.get_repo(repo_name)
        pr = repo.get_pull(pr_number)

        async with httpx.AsyncClient(timeout=30.0) as http_client:
            # Determine review type
            (
                is_incremental,
                base_commit_sha,
                review_state,
            ) = await _determine_review_type(db, repo_name, pr_number, pr, action)

            # Build dependencies
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

            # Post progress comment if needed
            await _post_progress_comment_if_needed(pr, action)

            # Run code review agent
            validated_result = await _run_code_review_agent(
                repo_name, pr_number, deps, agent
            )

            # Post inline comments if needed
            await _post_inline_comments_if_needed(pr, validated_result, deps)

            # Post summary review if needed
            await _post_summary_review_if_needed(
                pr, validated_result, deps, is_incremental
            )

            # Update review state in database
            await _update_review_state(
                db, repo_name, pr_number, pr, is_incremental, review_key
            )

            logger.info(
                f"Review completed for {review_key}: "
                f"{len(validated_result.comments)} comments, "
                f"recommendation: {validated_result.summary.recommendation}"
            )

    finally:
        db.close()
        logger.info(f"Finished review job for {review_key}")


# === HELPER FUNCTIONS ===


async def _determine_review_type(
    db: Session,
    repo_name: str,
    pr_number: int,
    pr: PullRequest,
    action: str,
) -> tuple[bool, str | None, ReviewState | None]:
    """
    Determine if review should be incremental or full.

    === BEHAVIOR ===

    Input:
        db: Database session
        repo_name: Repository full name
        pr_number: PR number
        pr: GitHub PR object
        action: Webhook action ("opened", "reopened", "synchronize")

    Output:
        Tuple of (is_incremental: bool, base_commit_sha: str | None, review_state: ReviewState | None)

    Logic Flow:

    INITIALIZE is_incremental = (action == "synchronize")
    INITIALIZE base_commit_sha = None
    INITIALIZE review_state = None

    IF is_incremental THEN
        QUERY ReviewState from database
            FILTER BY repo_full_name == repo_name AND pr_number == pr_number
            GET first result

        IF review_state exists AND initial_review_completed THEN
            SET base_commit_sha = review_state.last_reviewed_commit_sha
            LOG "Incremental review: comparing {base_commit_sha[:7]}..{pr.head.sha[:7]}"
        ELSE
            SET is_incremental = False
            LOG "First review for this PR - performing full review"

    RETURN (is_incremental, base_commit_sha, review_state)

    Edge Cases:
        - First synchronize event: Treated as full review
        - ReviewState missing: Treated as full review
    """
    is_incremental = action == "synchronize"
    base_commit_sha = None
    review_state = None

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
    """
    Post 'review in progress' comment for opened/reopened PRs.

    === BEHAVIOR ===

    Input:
        pr: GitHub PullRequest object
        action: Webhook action

    Output:
        None (side effect: posts comment to PR)

    Logic Flow:

    IF action IN {"opened", "reopened"} THEN
        GET bot_name FROM settings.bot_name
        BUILD progress_message = "🤖 **{bot_name}** is currently reviewing your PR..."
        POST comment to PR using pr.create_issue_comment()
        LOG "Posted 'review in progress' comment for PR #{pr.number}"
    ELSE
        LOG "Skipping progress comment for '{action}' event" (debug level)

    Edge Cases:
        - GitHub API fails: Exception propagates to caller
    """
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
    repo_name: str,
    pr_number: int,
    deps: ReviewDependencies,
    agent: Agent[ReviewDependencies, Any],
) -> CodeReviewResult:
    """
    Run the code review agent with exponential backoff retry.

    === BEHAVIOR ===

    Input:
        repo_name: Repository full name
        pr_number: PR number
        deps: ReviewDependencies (with cache, GitHub objects)
        agent: Code review agent instance

    Output:
        CodeReviewResult (validated)

    Logic Flow:

    LOG "Running AI code review for PR #{pr_number}"

    BUILD user_prompt = "Please review pull request #{pr_number} in {repo_name}. Analyze the changes and provide constructive feedback."

    CALL agent.run() with exponential backoff
        USE with_exponential_backoff wrapper
        PASS user_prompt and deps

    VALIDATE result using validate_review_result()
        PASS repo_full_name, pr_number, result.output

    RETURN validated CodeReviewResult

    Edge Cases:
        - Agent timeout: with_exponential_backoff retries
        - Invalid result format: validate_review_result raises error
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
    pr: PullRequest,
    validated_result: CodeReviewResult,
    deps: ReviewDependencies,
) -> None:
    """
    Post inline review comments to PR if agent didn't post them.

    === BEHAVIOR ===

    Input:
        pr: GitHub PullRequest object
        validated_result: Validated review result with comments
        deps: ReviewDependencies (with cache)

    Output:
        None (side effect: posts comments to PR)

    Logic Flow:

    CHECK if agent already posted comments
        IF deps._cache.get("inline_comments_posted", False) THEN
            LOG "Inline comments already posted by agent; skipping webhook inline posts"
            RETURN

    LOG "Posting {len(validated_result.comments)} inline comments"

    BUILD files_cache = {file.filename: file.patch for file in pr.get_files()}
    INITIALIZE posted_count = 0
    INITIALIZE skipped_count = 0

    IMPORT _is_line_in_diff from src.tools.github_tools

    FOR EACH comment IN validated_result.comments:
        GET file_patch from files_cache

        IF file_patch is None THEN
            LOG warning "Skipping comment on {file_path}:{line_number} - file not found in PR"
            INCREMENT skipped_count
            CONTINUE

        IF NOT _is_line_in_diff(file_patch, comment.line_number) THEN
            LOG warning "Skipping comment on {file_path}:{line_number} - line not in diff"
            INCREMENT skipped_count
            CONTINUE

        POST review comment
            CALL pr.create_review_comment()
            PASS body=comment.comment_body
            PASS commit=pr.head.sha
            PASS path=comment.file_path
            PASS line=comment.line_number

        LOG debug "Posted comment on {file_path}:{line_number}"
        INCREMENT posted_count

    LOG "Posted {posted_count} comments, skipped {skipped_count}"

    Edge Cases:
        - File not in PR: Skip comment (file may be renamed/deleted)
        - Line not in diff: Skip comment (GitHub API requirement)
        - Duplicate comments: GitHub may allow or reject (handle errors)
    """
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
    """
    Post summary review with approval status (APPROVE/REQUEST_CHANGES/COMMENT).

    === BEHAVIOR ===

    Input:
        pr: GitHub PullRequest object
        validated_result: Validated review result with summary
        deps: ReviewDependencies (with cache)
        is_incremental: Whether this is an incremental review

    Output:
        None (side effect: posts review to PR)

    Logic Flow:

    IF is_incremental THEN
        LOG "Skipping summary comment for incremental review (synchronize event)"
        RETURN

    BUILD summary_text = validated_result.format_summary_markdown()

    MAP approval status
        DEFINE approval_status_map = {
            "APPROVE": "APPROVE",
            "REQUEST_CHANGES": "REQUEST_CHANGES",
            "COMMENT": "COMMENT"
        }
        GET approval_status FROM approval_status_map[validated_result.summary.recommendation]
        DEFAULT to "COMMENT" if not found

    CHECK if agent already posted summary
        IF deps._cache.get("summary_review_posted", False) THEN
            LOG "Summary review already posted by agent; skipping webhook summary post"
        ELSE
            POST review to PR
                CALL pr.create_review()
                PASS body=summary_text
                PASS event=approval_status
            LOG "Posted summary review with status: {approval_status}"

    Edge Cases:
        - Incremental reviews: Always skip summary (noisy for small changes)
        - Invalid recommendation: Default to "COMMENT"
    """
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
    """
    Update or create ReviewState in database to track review progress.

    === BEHAVIOR ===

    Input:
        db: Database session
        repo_name: Repository full name
        pr_number: PR number
        pr: GitHub PullRequest object
        is_incremental: Whether this was an incremental review
        review_key: Human-readable key for logging

    Output:
        None (side effect: updates database)

    Logic Flow:

    QUERY existing ReviewState from database
        FILTER BY repo_full_name == repo_name AND pr_number == pr_number
        GET first result (using walrus operator: if review_state :=)

    IF review_state exists THEN
        UPDATE review state
            CALL review_state.update_review_state()
            PASS new_commit_sha=pr.head.sha
            PASS mark_initial_complete=(not is_incremental)
        LOG "Updated ReviewState for {review_key}: {pr.head.sha[:7]}"
    ELSE
        CREATE new ReviewState
            INITIALIZE with repo_full_name, pr_number
            SET last_reviewed_commit_sha = pr.head.sha
            SET initial_review_completed = True
        ADD to database session
        LOG "Created ReviewState for {review_key}: {pr.head.sha[:7]}"

    COMMIT database session

    Edge Cases:
        - First review: Creates new ReviewState
        - Incremental review: Updates existing state, doesn't mark initial complete
        - Database conflict: Commit may fail (let exception propagate)
    """
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
