"""Tools for conversation agent to interact with GitHub comments and code.

=== CONTEXT ===
Purpose: Provide conversation agent with tools to fetch code context and information
Reference: Similar to github_tools.py but focused on conversation-specific operations
Used by: conversation_agent.py

=== TOOLS PROVIDED ===
1. get_code_snippet_at_commit: Fetch code with context at specific commit
2. get_full_file_at_commit: Fetch entire file content at specific commit
3. get_comment_thread: Fetch full comment thread from GitHub
4. compare_code_versions: Compare code between two commits

All tools follow Pydantic AI tool pattern with RunContext.
"""

import logging
from typing import Any

from github.Repository import Repository

logger = logging.getLogger(__name__)

# TODO: IMPORT ConversationDependencies when defined in conversation_agent.py
# from src.models.conversation_dependencies import ConversationDependencies


def get_code_snippet_at_commit(
    ctx: Any,  # RunContext[ConversationDependencies]
    file_path: str,
    commit_sha: str,
    line_number: int,
    context_lines: int = 5,
) -> str:
    """
        Fetch code snippet with surrounding context at a specific commit.

        === PURPOSE ===
        Provide focused code context from a specific point in time
        Useful for showing "before" code when discussing changes

        === INPUT ===
        ctx: RunContext with ConversationDependencies
        file_path: Path to file in repository
        commit_sha: Git commit SHA to fetch from
        line_number: Target line number (1-indexed)
        context_lines: Number of lines before/after to include (default: 5)

        === OUTPUT ===
        Formatted string containing:
        - Line numbers
        - Code content
        - Highlight marker for target line
        - Error message if file not found

        === PRECONDITIONS ===
        - Repository object available in context
        - Valid commit SHA
        - File exists at that commit (may not exist anymore)

        === POSTCONDITIONS ===
        - Returns formatted snippet or error message
        - Logs access for debugging

        === LOGIC FLOW ===
        GET repository from context.deps
        LOG "Fetching code snippet: {file_path}:{line_number} @ {commit_sha[:7]}"

        TRY to fetch file content:
            GET file_content = repo.get_contents(file_path, ref=commit_sha)
            DECODE content to string
            SPLIT into lines

            VALIDATE line_number is within bounds
            IF line_number < 1 or line_number > total_lines THEN
                LOG warning "Line {line_number} out of bounds"
                SET line_number = clamp(line_number, 1, total_lines)

            CALCULATE start_line = max(1, line_number - context_lines)
            CALCULATE end_line = min(total_lines, line_number + context_lines)

            BUILD formatted snippet:
                SET output = []
                FOR each line from start_line to end_line:
                    FORMAT line_text = f"{line_num:4d}  {line_content}"
                    IF line_num == line_number THEN
                        PREPEND ">>> " to highlight target line
                    APPEND to output

            JOIN output lines with newlines
            RETURN formatted snippet

        EXCEPT UnknownObjectException:
            LOG "File not found: {file_path} @ {commit_sha[:7]}"
            RETURN f"[File '{file_path}' not found at commit {commit_sha[:7]} - may have been deleted or moved]"

        EXCEPT Exception as e:
            LOG error "Failed to fetch code snippet: {e}"
            RETURN f"[Error fetching code: {str(e)}]"

        === EDGE CASES ===
        - File deleted since commit: Return error message
        - Binary file: Return "[Binary file]"
        - Empty file: Return "[Empty file]"
        - Line number out of bounds: Clamp to valid range
        - Very large file: Only fetch needed lines (optimization)

        === EXAMPLE OUTPUT ===
        ```
          42  def process_user_data(user_id: str) -> dict:
          43      try:
          44          user = fetch_user(user_id)
    >>> 45          return user.to_dict()
          46      except UserNotFoundError:
          47          logger.warning(f"User {user_id} not found")
          48          return {}
        ```
    """
    # TODO: IMPLEMENT
    return "[Not implemented yet]"


def get_full_file_at_commit(
    ctx: Any,  # RunContext[ConversationDependencies]
    file_path: str,
    commit_sha: str,
) -> str:
    """
    Fetch entire file content at a specific commit.

    === PURPOSE ===
    Get complete file when snippet context isn't enough
    Use sparingly - prefer get_code_snippet_at_commit

    === INPUT ===
    ctx: RunContext with ConversationDependencies
    file_path: Path to file in repository
    commit_sha: Git commit SHA to fetch from

    === OUTPUT ===
    Full file content as string, or error message

    === LOGIC FLOW ===
    GET repository from context.deps
    LOG "Fetching full file: {file_path} @ {commit_sha[:7]}"

    TRY to fetch file:
        GET file_content = repo.get_contents(file_path, ref=commit_sha)
        DECODE content to string
        GET total_lines = count of lines

        IF total_lines > 500 THEN
            LOG warning "Large file ({total_lines} lines), consider using snippet tool"

        RETURN decoded content

    EXCEPT UnknownObjectException:
        LOG "File not found: {file_path} @ {commit_sha[:7]}"
        RETURN f"[File '{file_path}' not found at commit {commit_sha[:7]}]"

    EXCEPT Exception as e:
        LOG error "Failed to fetch file: {e}"
        RETURN f"[Error fetching file: {str(e)}]"

    === EDGE CASES ===
    - Very large files: Log warning but return content
    - Binary files: Return error message
    - Deleted files: Return error message

    === WHEN TO USE ===
    - User asks about overall file structure
    - Need to understand imports or class definitions
    - Discussing architectural changes

    === WHEN NOT TO USE ===
    - Only discussing specific lines (use get_code_snippet_at_commit)
    - File is very large (>1000 lines)
    """
    # TODO: IMPLEMENT
    return "[Not implemented yet]"


def get_comment_thread(
    ctx: Any,  # RunContext[ConversationDependencies]
    repo: Repository,
    pr_number: int,
    comment_id: int,
) -> list[dict[str, Any]]:
    """
    Fetch full comment thread from GitHub API.

    === PURPOSE ===
    Get all comments in a thread for context
    Useful when conversation history in database is incomplete

    === INPUT ===
    ctx: RunContext with ConversationDependencies
    repo: GitHub Repository object
    pr_number: Pull request number
    comment_id: Root comment ID of thread

    === OUTPUT ===
    List of comment dicts:
    [
        {
            "id": int,
            "user": str (login),
            "body": str,
            "created_at": str (ISO timestamp),
            "in_reply_to_id": int | None
        },
        ...
    ]

    === LOGIC FLOW ===
    LOG "Fetching comment thread for comment {comment_id}"

    TRY to fetch comments:
        GET pr = repo.get_pull(pr_number)
        GET all_comments = pr.get_review_comments()

        FILTER comments WHERE in_reply_to_id == comment_id OR id == comment_id
        SORT by created_at ascending

        BUILD thread list:
            FOR each comment in filtered_comments:
                APPEND {
                    "id": comment.id,
                    "user": comment.user.login,
                    "body": comment.body,
                    "created_at": comment.created_at.isoformat(),
                    "in_reply_to_id": comment.in_reply_to_id
                }

        RETURN thread list

    EXCEPT Exception as e:
        LOG error "Failed to fetch comment thread: {e}"
        RETURN []

    === EDGE CASES ===
    - Comment deleted: Return empty list
    - No replies: Return single comment
    - Nested replies: Flatten into chronological order

    === USAGE NOTES ===
    - Prefer using conversation_history from database (already formatted)
    - Use this tool when debugging or when database is unavailable
    - Thread structure is simple (one level of replies)
    """
    # TODO: IMPLEMENT
    return []


def compare_code_versions(
    ctx: Any,  # RunContext[ConversationDependencies]
    file_path: str,
    old_commit_sha: str,
    new_commit_sha: str,
    line_number: int,
    context_lines: int = 5,
) -> str:
    """
    Compare code between two commits and show diff.

    === PURPOSE ===
    Show user how code has changed since original review
    Useful when user says "I updated the code"

    === INPUT ===
    ctx: RunContext with ConversationDependencies
    file_path: Path to file
    old_commit_sha: Original commit when bot reviewed
    new_commit_sha: Current commit (usually PR head)
    line_number: Line to focus on
    context_lines: Context around line (default: 5)

    === OUTPUT ===
    Formatted diff showing before/after, or error message

    === LOGIC FLOW ===
    LOG "Comparing {file_path} between {old_commit_sha[:7]} and {new_commit_sha[:7]}"

    GET old_snippet = get_code_snippet_at_commit(..., old_commit_sha, ...)
    GET new_snippet = get_code_snippet_at_commit(..., new_commit_sha, ...)

    IF old_snippet starts with "[Error" OR new_snippet starts with "[Error" THEN
        RETURN "Could not compare - file may have been deleted or moved"

    IF old_snippet == new_snippet THEN
        RETURN "Code appears unchanged in this section"

    BUILD comparison output:
        APPEND "=== Before (commit {old_commit_sha[:7]}) ==="
        APPEND old_snippet
        APPEND ""
        APPEND "=== After (commit {new_commit_sha[:7]}) ==="
        APPEND new_snippet

    RETURN formatted comparison

    === EDGE CASES ===
    - File deleted: Return error message
    - File renamed: Won't detect automatically
    - No changes: Return "unchanged" message
    - One version missing: Return partial info

    === EXAMPLE OUTPUT ===
    ```
    === Before (commit a1b2c3d) ===
      42  def process_user_data(user_id: str):
      43      user = fetch_user(user_id)
    >>> 44      return user.to_dict()

    === After (commit e4f5g6h) ===
      42  def process_user_data(user_id: str) -> dict:
      43      try:
      44          user = fetch_user(user_id)
    >>> 45          return user.to_dict()
      46      except UserNotFoundError:
      47          return {}
    ```
    """
    # TODO: IMPLEMENT
    return "[Not implemented yet]"


# === HELPER FUNCTIONS ===


def _format_code_with_line_numbers(
    code_lines: list[str],
    start_line_number: int,
    highlight_line: int | None = None,
) -> str:
    """
    Format code with line numbers and optional highlight.

    === PURPOSE ===
    Consistent formatting for code snippets across tools

    === INPUT ===
    code_lines: List of code line strings
    start_line_number: Starting line number (1-indexed)
    highlight_line: Line to highlight with >>> (optional)

    === OUTPUT ===
    Formatted string with line numbers

    === LOGIC FLOW ===
    SET output = []
    FOR i, line in enumerate(code_lines):
        CALCULATE actual_line_num = start_line_number + i
        FORMAT line_text = f"{actual_line_num:4d}  {line.rstrip()}"

        IF actual_line_num == highlight_line THEN
            PREPEND ">>> " to line_text

        APPEND line_text to output

    JOIN output with newlines
    RETURN formatted string

    === EXAMPLE OUTPUT ===
    ```
      42  def example():
      43      x = 1
    >>> 44      return x
      45
    ```
    """
    # TODO: IMPLEMENT
    return ""
