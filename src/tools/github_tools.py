"""GitHub interaction tools for the code review agent."""

import logging
import re
from typing import Any, Literal, cast

from github.PullRequest import PullRequest
from github.Repository import Repository
from pydantic_ai import RunContext

from src.models.dependencies import ReviewDependencies
from src.models.github_types import FileDiff, PRContext

logger = logging.getLogger(__name__)


def _get_repo_and_pr(
    ctx: RunContext[ReviewDependencies],
) -> tuple[Repository, PullRequest]:
    """Get repository and pull request objects from context.

    Caches the objects to avoid redundant API calls during a review run.

    Args:
        ctx: Run context with ReviewDependencies

    Returns:
        Tuple of (Repository, PullRequest)

    Raises:
        GithubException: If GitHub API request fails
    """
    # Return cached objects if available
    if ctx.deps.repo is not None and ctx.deps.pr is not None:
        return ctx.deps.repo, ctx.deps.pr

    # Fetch and cache
    github_client = ctx.deps.github_client
    repo_full_name = ctx.deps.repo_full_name
    pr_number = ctx.deps.pr_number

    repo = github_client.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)

    # Cache for future calls
    ctx.deps.repo = repo
    ctx.deps.pr = pr

    logger.debug(f"Cached repo and PR objects for {repo_full_name}#{pr_number}")

    return repo, pr


async def fetch_pr_context(ctx: RunContext[ReviewDependencies]) -> dict[str, Any]:
    """Fetch PR metadata and context.

    Args:
        ctx: Run context with ReviewDependencies

    Returns:
        Dictionary with PR context data

    Raises:
        GithubException: If GitHub API request fails
    """
    repo, pr = _get_repo_and_pr(ctx)

    # Extract PR data and create PRContext
    context = PRContext(
        number=pr.number,
        title=pr.title,
        description=pr.body or "",
        author=pr.user.login,
        files_changed=pr.changed_files,
        additions=pr.additions,
        deletions=pr.deletions,
        commits=pr.commits,
        labels=[label.name for label in pr.labels],
        base_branch=pr.base.ref,
        head_branch=pr.head.ref,
    )

    logger.info(f"Fetched PR context for #{pr.number} in {ctx.deps.repo_full_name}")
    return context.model_dump()


async def list_changed_files(ctx: RunContext[ReviewDependencies]) -> list[str]:
    """List all files changed in the PR.

    Args:
        ctx: Run context with ReviewDependencies

    Returns:
        List of changed file paths

    Raises:
        GithubException: If GitHub API request fails
    """
    _, pr = _get_repo_and_pr(ctx)

    # Get files
    files = pr.get_files()
    filenames = [file.filename for file in files]

    logger.info(f"Found {len(filenames)} changed files in PR #{pr.number}")
    return filenames


async def get_file_diff(
    ctx: RunContext[ReviewDependencies], file_path: str
) -> dict[str, Any]:
    """Get the diff/patch for a specific file.

    Args:
        ctx: Run context with ReviewDependencies
        file_path: Path to the file

    Returns:
        Dictionary with file diff data

    Raises:
        ValueError: If file is not found in the PR
        GithubException: If GitHub API request fails
    """
    _, pr = _get_repo_and_pr(ctx)

    # Find matching file
    files = pr.get_files()
    target_file = None
    for file in files:
        if file.filename == file_path:
            target_file = file
            break

    # If not found
    if target_file is None:
        raise ValueError(f"File not found in PR: {file_path}")

    # Create FileDiff model
    # PyGithub returns status as str, cast to Literal type for FileDiff
    file_diff = FileDiff(
        filename=target_file.filename,
        status=cast(
            Literal["added", "modified", "removed", "renamed"], target_file.status
        ),
        additions=target_file.additions,
        deletions=target_file.deletions,
        changes=target_file.changes,
        patch=target_file.patch or "",
        previous_filename=target_file.previous_filename,
    )

    logger.info(
        f"Retrieved diff for {file_path} "
        f"({file_diff.status}, +{file_diff.additions}/-{file_diff.deletions})"
    )
    return file_diff.model_dump()


async def get_full_file(
    ctx: RunContext[ReviewDependencies], file_path: str, ref: str = "head"
) -> str:
    """Get complete file content at head or base revision.

    Args:
        ctx: Run context with ReviewDependencies
        file_path: Path to the file
        ref: Reference to get file from ("head" or "base")

    Returns:
        File content as string

    Raises:
        ValueError: If ref is invalid, path is a directory, or file is binary
        GithubException: If GitHub API request fails
    """
    # Validate ref
    if ref not in ("head", "base"):
        raise ValueError(f"Invalid ref '{ref}', must be 'head' or 'base'")

    repo, pr = _get_repo_and_pr(ctx)

    # Determine SHA based on ref
    sha = pr.head.sha if ref == "head" else pr.base.sha

    # Get file content
    content = repo.get_contents(file_path, ref=sha)

    # Handle directory case
    if isinstance(content, list):
        raise ValueError(f"{file_path} is a directory, not a file")

    # Decode content
    try:
        file_content = str(content.decoded_content.decode("utf-8"))
    except UnicodeDecodeError as e:
        raise ValueError(f"{file_path} is a binary file") from e

    logger.info(
        f"Retrieved full content of {file_path} at {ref} ({len(file_content)} bytes)"
    )
    return file_content


def _is_line_in_diff(patch: str | None, line_number: int) -> bool:
    """Check if a line number exists in the diff patch.

    Args:
        patch: The diff patch string
        line_number: The line number to check

    Returns:
        True if the line is in the diff, False otherwise
    """
    if not patch:
        return False

    # Simple parser
    # Iterate through lines
    lines = patch.split("\n")
    current_new_line = 0

    # Regex for hunk header: @@ -old_start,old_len +new_start,new_len @@
    # Note: len is optional if it is 1
    hunk_header_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    in_hunk = False

    for line in lines:
        if line.startswith("@@"):
            match = hunk_header_re.match(line)
            if match:
                current_new_line = int(match.group(1))
                in_hunk = True
                continue

        if not in_hunk:
            continue

        if line.startswith("+") or line.startswith(" "):
            # This line corresponds to current_new_line
            if current_new_line == line_number:
                return True
            current_new_line += 1
        elif line.startswith("-"):
            # This line is in old file, doesn't advance new file line count
            pass

    return False


async def post_review_comment(
    ctx: RunContext[ReviewDependencies],
    file_path: str,
    line_number: int,
    comment_body: str,
) -> str:
    """Post inline comment on specific line of code.

    Args:
        ctx: Run context with ReviewDependencies
        file_path: Path to the file
        line_number: Line number to comment on
        comment_body: Comment text

    Returns:
        Success message

    Raises:
        ValueError: If file not found in PR or line not in diff
        GithubException: If GitHub API request fails
    """
    _, pr = _get_repo_and_pr(ctx)

    # Validate line number against diff
    files = pr.get_files()
    target_file = None
    for file in files:
        if file.filename == file_path:
            target_file = file
            break

    if not target_file:
        raise ValueError(f"File {file_path} not found in PR")

    if not _is_line_in_diff(target_file.patch, line_number):
        raise ValueError(
            f"Line {line_number} in {file_path} is not part of the diff. "
            "You can only comment on changed lines or context lines visible in the diff. "
            "Please check `get_file_diff` to find valid line numbers."
        )

    # Get latest commit
    commits = list(pr.get_commits())
    latest_commit = commits[-1]  # Get most recent commit

    # Create review comment
    pr.create_review_comment(
        body=comment_body, commit=latest_commit, path=file_path, line=line_number
    )

    logger.info(f"Posted review comment on {file_path}:{line_number}")
    return f"Posted comment on {file_path}:{line_number}"


async def post_summary_comment(
    ctx: RunContext[ReviewDependencies],
    summary: str,
    approval_status: str = "COMMENT",
) -> str:
    """Post overall review summary with approval status.

    This makes the bot appear in the Reviewers section on GitHub!

    Args:
        ctx: Run context with ReviewDependencies
        summary: Review summary text
        approval_status: "APPROVE", "REQUEST_CHANGES", or "COMMENT"

    Returns:
        Success message

    Raises:
        ValueError: If approval_status is invalid
        GithubException: If GitHub API request fails
    """
    # Validate approval_status
    valid_statuses = ["APPROVE", "REQUEST_CHANGES", "COMMENT"]
    if approval_status not in valid_statuses:
        raise ValueError(
            f"Invalid approval_status '{approval_status}'. Must be one of {valid_statuses}"
        )

    _, pr = _get_repo_and_pr(ctx)

    # Create review
    pr.create_review(body=summary, event=approval_status)

    logger.info(
        f"Posted review summary for PR #{pr.number} with status: {approval_status}"
    )
    return f"Posted review with status: {approval_status}"
