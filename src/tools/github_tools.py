"""GitHub interaction tools for the code review agent."""

import logging
import re
from typing import Any, Literal, cast

from github import GithubException
from pydantic_ai import RunContext

from src.models.dependencies import ReviewDependencies
from src.models.github_types import FileDiff, PRContext

logger = logging.getLogger(__name__)


async def fetch_pr_context(ctx: RunContext[ReviewDependencies]) -> dict[str, Any]:
    """Fetch PR metadata and context.

    Args:
        ctx: Run context with ReviewDependencies

    Returns:
        Dictionary with PR context data

    Raises:
        GithubException: If GitHub API request fails
    """
    github_client = ctx.deps.github_client
    repo_full_name = ctx.deps.repo_full_name
    pr_number = ctx.deps.pr_number

    # Get repo and PR
    repo = github_client.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)

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

    logger.info(f"Fetched PR context for #{pr_number} in {repo_full_name}")
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
    github_client = ctx.deps.github_client
    repo_full_name = ctx.deps.repo_full_name
    pr_number = ctx.deps.pr_number

    # Get repo and PR
    repo = github_client.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)

    # Get files
    files = pr.get_files()
    filenames = [file.filename for file in files]

    logger.info(f"Found {len(filenames)} changed files in PR #{pr_number}")
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
    github_client = ctx.deps.github_client
    repo_full_name = ctx.deps.repo_full_name
    pr_number = ctx.deps.pr_number

    # Get repo and PR
    repo = github_client.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)

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
        File content as string or error message
    """
    try:
        github_client = ctx.deps.github_client
        repo_full_name = ctx.deps.repo_full_name
        pr_number = ctx.deps.pr_number

        # Get repo and PR
        repo = github_client.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)

        # Determine SHA based on ref
        if ref == "head":
            sha = pr.head.sha
        elif ref == "base":
            sha = pr.base.sha
        else:
            return f"Error: Invalid ref '{ref}', must be 'head' or 'base'"

        # Get file content
        content = repo.get_contents(file_path, ref=sha)

        # Handle directory case
        if isinstance(content, list):  # Directory
            return f"Error: {file_path} is a directory, not a file"

        # Decode content
        try:
            file_content = str(content.decoded_content.decode("utf-8"))
            logger.info(
                f"Retrieved full content of {file_path} at {ref} ({len(file_content)} bytes)"
            )
            return file_content
        except UnicodeDecodeError:
            return f"Error: {file_path} is a binary file"

    except GithubException as e:
        if e.status == 404:
            return f"Error: File {file_path} not found at {ref}"
        logger.error(f"GitHub API error getting full file: {e}")
        return f"Error: GitHub API error: {e}"
    except Exception as e:
        logger.error(f"Unexpected error getting full file: {e}")
        return f"Error: Unexpected error: {e}"


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
        Success message or error message
    """
    try:
        github_client = ctx.deps.github_client
        repo_full_name = ctx.deps.repo_full_name
        pr_number = ctx.deps.pr_number

        # Get repo and PR
        repo = github_client.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)

        # Validate line number against diff
        files = pr.get_files()
        target_file = None
        for file in files:
            if file.filename == file_path:
                target_file = file
                break

        if not target_file:
            return f"Error: File {file_path} not found in PR"

        if not _is_line_in_diff(target_file.patch, line_number):
            return (
                f"Error: Line {line_number} in {file_path} is not part of the diff. "
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

    except GithubException as e:
        logger.error(f"GitHub API error posting comment: {e}")
        return f"Error: GitHub API error: {e}"
    except Exception as e:
        logger.error(f"Unexpected error posting comment: {e}")
        return f"Error: Unexpected error: {e}"


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
        Success message or error message
    """
    # Validate approval_status
    valid_statuses = ["APPROVE", "REQUEST_CHANGES", "COMMENT"]
    if approval_status not in valid_statuses:
        return f"Error: Invalid approval_status '{approval_status}'. Must be one of {valid_statuses}"

    try:
        github_client = ctx.deps.github_client
        repo_full_name = ctx.deps.repo_full_name
        pr_number = ctx.deps.pr_number

        # Get repo and PR
        repo = github_client.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)

        # Create review
        pr.create_review(body=summary, event=approval_status)

        logger.info(
            f"Posted review summary for PR #{pr_number} with status: {approval_status}"
        )
        return f"Posted review with status: {approval_status}"

    except GithubException as e:
        logger.error(f"GitHub API error posting review: {e}")
        return f"Error: GitHub API error: {e}"
    except Exception as e:
        logger.error(f"Unexpected error posting review: {e}")
        return f"Error: Unexpected error: {e}"
