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
    if session_factory is None:
        session_factory = SessionLocal
    if github_auth is None:
        from src.services.github_auth import get_github_app_auth

        github_auth = get_github_app_auth()
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


# === HELPER FUNCTIONS ===


async def _determine_review_type(
    db: Session,
    repo_name: str,
    pr_number: int,
    pr: PullRequest,
    action: str,
) -> tuple[bool, str | None, ReviewState | None]:
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
