import logging
from typing import Any, cast

from github.ContentFile import ContentFile
from github.Repository import Repository
from pydantic_ai import RunContext

from src.models.dependencies import ConversationDependencies

logger = logging.getLogger(__name__)


def get_code_snippet_at_commit(
    ctx: RunContext[ConversationDependencies],
    file_path: str,
    commit_sha: str,
    line_number: int,
    context_lines: int = 5,
) -> str:
    # Get repository from context
    repo = ctx.deps.repo
    if not repo:
        logger.error("Repository not available in context")
        return "[Error: Repository not available]"

    logger.info(f"Fetching code snippet: {file_path}:{line_number} @ {commit_sha[:7]}")

    # Fetch file content at specific commit
    # get_contents returns ContentFile | list[ContentFile], cast to ContentFile for single files
    file_content = cast(ContentFile, repo.get_contents(file_path, ref=commit_sha))

    # Check if binary file
    if file_content.encoding != "base64":
        return "[Binary file - cannot display content]"

    # Decode content to string
    decoded_content = file_content.decoded_content.decode("utf-8")

    # Handle empty file
    if not decoded_content.strip():
        return "[Empty file]"

    # Split into lines
    lines = decoded_content.splitlines()
    total_lines = len(lines)

    # Validate and clamp line number
    if line_number < 1:
        logger.warning(f"Line number {line_number} < 1, clamping to 1")
        line_number = 1
    elif line_number > total_lines:
        logger.warning(
            f"Line number {line_number} > {total_lines}, clamping to {total_lines}"
        )
        line_number = total_lines

    # Calculate range with bounds checking
    start_line = max(1, line_number - context_lines)
    end_line = min(total_lines, line_number + context_lines)

    # Build formatted snippet with line numbers
    output = []
    for i in range(start_line - 1, end_line):  # -1 because lines are 0-indexed
        actual_line_num = i + 1
        line_content = lines[i]

        # Format with line number
        formatted_line = f"{actual_line_num:4d}  {line_content}"

        # Add highlight marker for target line
        if actual_line_num == line_number:
            formatted_line = f">>> {formatted_line}"
        else:
            formatted_line = f"    {formatted_line}"

        output.append(formatted_line)

    return "\n".join(output)


def get_full_file_at_commit(
    ctx: RunContext[ConversationDependencies],
    file_path: str,
    commit_sha: str,
) -> str:
    # Get repository from context
    repo = ctx.deps.repo
    if not repo:
        logger.error("Repository not available in context")
        return "[Error: Repository not available]"

    logger.info(f"Fetching full file: {file_path} @ {commit_sha[:7]}")

    # Fetch file content
    # get_contents returns ContentFile | list[ContentFile], cast to ContentFile for single files
    file_content = cast(ContentFile, repo.get_contents(file_path, ref=commit_sha))

    # Check if binary file
    if file_content.encoding != "base64":
        return "[Binary file - cannot display content]"

    # Decode content to string
    decoded_content = file_content.decoded_content.decode("utf-8")
    total_lines = len(decoded_content.splitlines())

    # Warn if large file
    if total_lines > 500:
        logger.warning(f"Large file ({total_lines} lines), consider using snippet tool")

    return decoded_content


def get_comment_thread(
    ctx: RunContext[ConversationDependencies],
    repo: Repository,
    pr_number: int,
    comment_id: int,
) -> list[dict[str, Any]]:
    logger.info(f"Fetching comment thread for comment {comment_id}")

    # Fetch PR and all review comments
    pr = repo.get_pull(pr_number)
    all_comments = pr.get_review_comments()

    # Filter comments in this thread
    thread_comments = [
        c for c in all_comments if c.id == comment_id or c.in_reply_to_id == comment_id
    ]

    # Sort by creation time
    thread_comments.sort(key=lambda c: c.created_at)

    # Build thread list
    thread = []
    for comment in thread_comments:
        thread.append(
            {
                "id": comment.id,
                "user": comment.user.login,
                "body": comment.body,
                "created_at": comment.created_at.isoformat(),
                "in_reply_to_id": comment.in_reply_to_id,
            }
        )

    return thread


def compare_code_versions(
    ctx: RunContext[ConversationDependencies],
    file_path: str,
    old_commit_sha: str,
    new_commit_sha: str,
    line_number: int,
    context_lines: int = 5,
) -> str:
    logger.info(
        f"Comparing {file_path} between {old_commit_sha[:7]} and {new_commit_sha[:7]}"
    )

    # Get both snippets
    old_snippet = get_code_snippet_at_commit(
        ctx, file_path, old_commit_sha, line_number, context_lines
    )
    new_snippet = get_code_snippet_at_commit(
        ctx, file_path, new_commit_sha, line_number, context_lines
    )

    # Check for errors
    if old_snippet.startswith("[Error") or new_snippet.startswith("[Error"):
        return "Could not compare - file may have been deleted or moved"

    # Check if unchanged
    if old_snippet == new_snippet:
        return "Code appears unchanged in this section"

    # Build comparison output
    comparison = [
        f"=== Before (commit {old_commit_sha[:7]}) ===",
        old_snippet,
        "",
        f"=== After (commit {new_commit_sha[:7]}) ===",
        new_snippet,
    ]

    return "\n".join(comparison)


# === HELPER FUNCTIONS ===


def _format_code_with_line_numbers(
    code_lines: list[str],
    start_line_number: int,
    highlight_line: int | None = None,
) -> str:
    output = []
    for i, line in enumerate(code_lines):
        actual_line_num = start_line_number + i
        line_text = f"{actual_line_num:4d}  {line.rstrip()}"

        # Add highlight if this is the target line
        if actual_line_num == highlight_line:
            line_text = f">>> {line_text}"
        else:
            line_text = f"    {line_text}"

        output.append(line_text)

    return "\n".join(output)
