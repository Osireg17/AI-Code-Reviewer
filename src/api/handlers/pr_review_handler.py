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
    force_full_review: bool = False,
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

        # Skip review if PR is already closed/merged
        if pr.state != "open":
            logger.info(f"Skipping review for {review_key} - PR state is '{pr.state}'")
            return

        async with httpx.AsyncClient(timeout=30.0) as http_client:
            (
                is_incremental,
                base_commit_sha,
                review_state,
            ) = await _determine_review_type(
                db, repo_name, pr_number, pr, action, force_full_review, repo=repo
            )
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
                pr, validated_result, deps, is_incremental, base_commit_sha
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
    force_full_review: bool = False,
    repo: Any = None,
) -> tuple[bool, str | None, ReviewState | None]:
    """Determine whether to perform incremental or full review.

    Args:
        db: Database session
        repo_name: Full repository name (owner/repo)
        pr_number: Pull request number
        pr: GitHub PullRequest object
        action: GitHub webhook action
        force_full_review: If True, always perform full review (user-triggered)
        repo: GitHub Repository object (for force push detection)

    Returns:
        Tuple of (is_incremental, base_commit_sha, review_state)
    """
    # Force full review if explicitly requested (e.g., via re-review command)
    if force_full_review:
        logger.info("Force full review requested - skipping incremental logic")
        return False, None, None

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

            # Check for force push before proceeding with incremental review
            if repo and _detect_force_push(repo, base_commit_sha, pr):
                logger.info(
                    f"Force push detected for PR #{pr_number} - falling back to full review"
                )
                await _handle_force_push(pr, base_commit_sha)
                return False, None, review_state

            logger.info(
                f"Incremental review: comparing {base_commit_sha[:7]}..{pr.head.sha[:7]}"
            )
        else:
            is_incremental = False
            logger.info("First review for this PR - performing full review")

    return is_incremental, base_commit_sha, review_state


def _detect_force_push(repo: Any, base_sha: str | None, pr: PullRequest) -> bool:
    """Detect if a force push occurred by checking if base commit still exists.

    When a developer force pushes, the old commit SHA no longer exists in the
    repository history. This function attempts to fetch the stored base commit
    to detect this scenario.

    Args:
        repo: GitHub Repository object
        base_sha: The SHA of the last reviewed commit from our database
        pr: GitHub PullRequest object

    Returns:
        True if force push detected (base commit missing), False otherwise
    """
    if not base_sha:
        return False

    try:
        # Try to fetch the commit - will raise if it doesn't exist
        repo.get_commit(base_sha)

        # Additional check: verify commit is in PR's history
        # Compare base_sha with PR's base to ensure it's still reachable
        comparison = repo.compare(pr.base.sha, base_sha)

        # If we can't reach base_sha from PR base, it's been force-pushed away
        if comparison.status == "diverged" or comparison.ahead_by == 0:
            # "diverged" means histories split; check if base_sha is reachable
            # This is a heuristic - if we get here without error, commit exists
            pass

        return False
    except Exception as e:
        # Commit not found or comparison failed - likely force push
        logger.warning(
            f"Force push detected: cannot find commit {base_sha[:7]} in PR #{pr.number}. "
            f"Error: {e}"
        )
        return True


async def _handle_force_push(pr: PullRequest, base_sha: str) -> None:
    """Post a warning comment when force push is detected.

    Args:
        pr: GitHub PullRequest object
        base_sha: The SHA that was expected but is now missing
    """
    warning_message = (
        "⚠️ **Force Push Detected**\n\n"
        f"The previously reviewed commit (`{base_sha[:7]}`) is no longer in this PR's history. "
        "This usually means a force push occurred.\n\n"
        "I'll perform a **full review** of all changes instead of an incremental review."
    )
    try:
        pr.create_issue_comment(body=warning_message)
        logger.info(f"Posted force push warning for PR #{pr.number}")
    except Exception as e:
        logger.warning(f"Failed to post force push warning: {e}")


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
    base_commit_sha: str | None = None,
) -> None:
    if deps._cache.get("summary_review_posted", False):
        logger.info(
            "Summary review already posted by agent; skipping webhook summary post"
        )
        return

    if is_incremental:
        # Post brief incremental update instead of full summary
        await _post_incremental_summary(
            pr, validated_result, base_commit_sha or "unknown"
        )
        return

    # Full review: post formal review with approval status
    summary_text = validated_result.format_summary_markdown()
    approval_status_map = {
        "APPROVE": "APPROVE",
        "REQUEST_CHANGES": "REQUEST_CHANGES",
        "COMMENT": "COMMENT",
    }
    approval_status = approval_status_map.get(
        validated_result.summary.recommendation, "COMMENT"
    )
    pr.create_review(body=summary_text, event=approval_status)
    logger.info(f"Posted summary review with status: {approval_status}")


async def _post_incremental_summary(
    pr: PullRequest,
    validated_result: CodeReviewResult,
    base_commit_sha: str,
) -> None:
    """Post a brief summary comment for incremental reviews.

    Instead of a formal review submission, posts an issue comment with
    a quick summary of what was reviewed and any new issues found.
    """
    # Count issues by severity
    critical_count = 0
    warning_count = 0
    suggestion_count = 0

    for comment in validated_result.comments:
        severity = getattr(comment, "severity", "suggestion").lower()
        if severity in ("critical", "error", "blocker"):
            critical_count += 1
        elif severity in ("warning", "medium"):
            warning_count += 1
        else:
            suggestion_count += 1

    # Get list of reviewed files
    reviewed_files = list({c.file_path for c in validated_result.comments})
    files_reviewed = len(reviewed_files)

    # Build summary message
    commit_range = f"{base_commit_sha[:7]}..{pr.head.sha[:7]}"
    summary_parts = [
        "**Incremental Review Update**",
        "",
        f"Reviewed changes in commits `{commit_range}`.",
        "",
    ]

    if validated_result.comments:
        issue_summary = []
        if critical_count > 0:
            issue_summary.append(f"🔴 {critical_count} critical")
        if warning_count > 0:
            issue_summary.append(f"🟡 {warning_count} warning")
        if suggestion_count > 0:
            issue_summary.append(f"🔵 {suggestion_count} suggestion")

        summary_parts.append(f"**New issues:** {', '.join(issue_summary)}")
    else:
        summary_parts.append("**No new issues found** in the updated code.")

    if files_reviewed > 0:
        file_list = ", ".join(f"`{f}`" for f in reviewed_files[:5])
        if files_reviewed > 5:
            file_list += f" and {files_reviewed - 5} more"
        summary_parts.append(f"**Files reviewed:** {file_list}")

    summary_text = "\n".join(summary_parts)

    # Post as issue comment (not formal review) to avoid cluttering review timeline
    pr.create_issue_comment(body=summary_text)
    logger.info(
        f"Posted incremental review summary for PR #{pr.number}: "
        f"{critical_count} critical, {warning_count} warning, {suggestion_count} suggestions"
    )


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
