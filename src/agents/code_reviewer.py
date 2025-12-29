"""Code review agent using Pydantic AI and OpenAI."""

import logging
import os
from typing import cast

from pydantic_ai import Agent, RunContext

from src.config.settings import settings
from src.models.dependencies import ReviewDependencies
from src.models.outputs import CodeReviewResult
from src.prompts.code_reviewer_prompt import SYSTEM_PROMPT
from src.tools import conversation_tools, github_tools, rag_tools

logger = logging.getLogger(__name__)


# Set OpenAI API key as environment variable for Pydantic AI
if settings.openai_api_key:
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key

# Create the code review agent
code_review_agent = Agent(
    model=f"openai:{settings.openai_model}",
    deps_type=ReviewDependencies,
    output_type=CodeReviewResult,
    system_prompt=SYSTEM_PROMPT,
    retries=settings.max_retries,
)


@code_review_agent.tool
async def fetch_pr_context(ctx: RunContext[ReviewDependencies]) -> dict:
    """Fetch PR metadata and context.

    This result is cached to avoid redundant API calls.
    """
    cache_key = "pr_context"
    if cache_key in ctx.deps._cache:
        logger.debug(f"Returning cached PR context for PR #{ctx.deps.pr_number}")
        return cast(dict, ctx.deps._cache[cache_key])

    result = await github_tools.fetch_pr_context(ctx)
    ctx.deps._cache[cache_key] = result
    logger.debug(f"Cached PR context for PR #{ctx.deps.pr_number}")
    return result


@code_review_agent.tool
async def list_changed_files(ctx: RunContext[ReviewDependencies]) -> list[str]:
    """List all files changed in the PR.

    This result is cached to avoid redundant API calls.
    For incremental reviews, only returns files changed since last review.
    """
    cache_key = "changed_files"
    if cache_key in ctx.deps._cache:
        logger.debug(f"Returning cached file list for PR #{ctx.deps.pr_number}")
        return cast(list[str], ctx.deps._cache[cache_key])

    result = await github_tools.list_changed_files(ctx)
    ctx.deps._cache[cache_key] = result
    logger.debug(f"Cached {len(result)} changed files for PR #{ctx.deps.pr_number}")
    return result


@code_review_agent.tool
async def check_should_review_file(
    ctx: RunContext[ReviewDependencies], file_path: str
) -> dict:
    """Check if a file should be reviewed based on type and content.

    Use this tool BEFORE reviewing each file to determine if it should be skipped.
    This will skip lock files, minified files, generated code, binaries, etc.

    Returns dict with:
        - should_review: bool - whether to review this file
        - file_type: str - type of file (e.g., "code file", "config file")
        - reason: str or None - reason for skipping if should_review is False
    """
    return await github_tools.check_should_review_file(ctx, file_path)


@code_review_agent.tool
async def get_file_diff(ctx: RunContext[ReviewDependencies], file_path: str) -> dict:
    """Get the diff/patch for a specific file.

    This result is cached per file_path to avoid redundant API calls.

    Returns:
        Dict with:
            - filename: str
            - status: str (added/modified/removed/renamed)
            - additions: int
            - deletions: int
            - changes: int
            - patch: str (diff content)
            - valid_comment_lines: list[int] - **USE THIS to know which lines you can comment on**

    CRITICAL: Only post comments on line numbers found in valid_comment_lines.
    """
    cache_key = f"diff:{file_path}"
    if cache_key in ctx.deps._cache:
        logger.debug(f"Returning cached diff for {file_path}")
        return cast(dict, ctx.deps._cache[cache_key])

    result = await github_tools.get_file_diff(ctx, file_path)
    ctx.deps._cache[cache_key] = result
    logger.debug(f"Cached diff for {file_path}")
    return result


@code_review_agent.tool
async def get_full_file(
    ctx: RunContext[ReviewDependencies], file_path: str, ref: str = "head"
) -> str:
    """Get complete file content at head or base revision."""
    return await github_tools.get_full_file(ctx, file_path, ref)


@code_review_agent.tool
async def post_review_comment(
    ctx: RunContext[ReviewDependencies],
    file_path: str,
    line_number: int,
    comment_body: str,
) -> str:
    """Post inline comment on specific line of code."""
    return await github_tools.post_review_comment(
        ctx, file_path, line_number, comment_body
    )


@code_review_agent.tool
async def post_summary_comment(
    ctx: RunContext[ReviewDependencies],
    summary: str,
    approval_status: str = "COMMENT",
) -> str:
    """Post overall review summary with approval status."""
    return await github_tools.post_summary_comment(ctx, summary, approval_status)


# Register RAG tool


@code_review_agent.tool
async def search_style_guides(
    ctx: RunContext[ReviewDependencies],
    query: str,
    language: str | None = None,
    top_k: int = 3,
) -> dict:
    """Search coding style guides and best practices for a specific language.

    Use this tool to find authoritative guidance on:
    - Naming conventions (variables, functions, classes)
    - Design patterns and idioms
    - Security best practices
    - Error handling patterns
    - Code organization and structure
    - Language-specific anti-patterns to avoid

    Args:
        query: Natural language question (e.g., "exception handling patterns")
        language: Programming language (e.g., "python", "java", "javascript")
        top_k: Number of results (default: 3)

    Returns:
        Dict with results array containing style guide excerpts with sources

    Example usage:
        search_style_guides(query="naming conventions for constants", language="java")
    """
    return await rag_tools.search_style_guides(ctx, query, language, top_k)


@code_review_agent.tool
async def suggest_code_fix(
    ctx: RunContext[ReviewDependencies],
    explanation: str,
    new_code: str,
    issue_category: str,
    file_path: str,
) -> str:
    """
    Format a code fix as GitHub's suggestion markdown with "Commit suggestion" button.

    Use this tool ONLY when you've identified a CLEAR violation of coding conventions
    (e.g., PEP 8 naming, style guide rules) and want to provide a ready-to-commit fix.

    You (the agent) must generate the corrected code using your reasoning, then call
    this tool to format it as a GitHub suggestion with RAG-backed citations.

    Args:
        explanation: Description of the violation (e.g., "Variable name violates PEP 8 snake_case convention")
        new_code: The corrected code you've generated (e.g., "user_data = get_user_info()")
        issue_category: Type of issue (e.g., "naming", "type_hint", "import", "formatting")
        file_path: Path to the file being reviewed (e.g., "src/main.py") - used for language detection

    Returns:
        Formatted GitHub suggestion markdown with citation (if RAG finds relevant style guide)

    When to use:
        ✅ Clear naming convention violations (camelCase → snake_case in Python)
        ✅ Missing/incorrect type hints with obvious fixes
        ✅ Import ordering/formatting per style guide
        ✅ Simple formatting issues (quotes, spacing)

    When NOT to use:
        ❌ Complex refactoring or architectural changes
        ❌ Business logic modifications
        ❌ Subjective style preferences without style guide backing
        ❌ Multi-line changes affecting control flow

    Example usage:
        Reviewing file: src/utils.py
        User has: userData = getUserInfo()
        Agent reasoning: Variable violates PEP 8, should be user_data
        -> Call suggest_code_fix(
            explanation="Variable name violates PEP 8 snake_case convention",
            new_code="user_data = get_user_info()",
            issue_category="naming",
            file_path="src/utils.py"
        )

    Output: GitHub renders inline suggestion with "Commit suggestion" button
    """
    # DELEGATE to conversation_tools.suggest_code_fix (shared implementation)
    # This will:
    # - DETECT language from file_path
    # - SEARCH RAG for style guide citations
    # - FORMAT as GitHub suggestion markdown
    # - RETURN formatted string
    return await conversation_tools.suggest_code_fix(
        ctx=ctx,
        explanation=explanation,
        new_code=new_code,
        issue_category=issue_category,
        file_path=file_path,
    )


@code_review_agent.system_prompt
async def add_dynamic_context(ctx: RunContext[ReviewDependencies]) -> str:
    """Add dynamic context based on PR metadata.

    Provides repo-specific information and constraints to the agent
    based on the current ReviewDependencies.

    Args:
        ctx: Run context with ReviewDependencies

    Returns:
        Additional system prompt text with dynamic context
    """
    max_files = settings.max_files_per_review

    return f"""
Repo: {ctx.deps.repo_full_name} | PR: #{ctx.deps.pr_number} | Max files: {max_files}

If >{max_files} files: prioritize security/auth, core logic, APIs. Skip generated/lock files.
"""


def validate_review_result(
    repo_full_name: str, pr_number: int, result: CodeReviewResult
) -> CodeReviewResult:
    """Validate and correct the review result.

    Ensures the ReviewSummary counts match the actual comments,
    logs the review completion, and returns a corrected result.

    Args:
        repo_full_name: Repository full name
        pr_number: PR number
        result: The agent's review result

    Returns:
        Corrected CodeReviewResult with accurate counts
    """
    # Count actual comments by severity
    actual_critical = sum(1 for c in result.comments if c.severity == "critical")
    actual_warnings = sum(1 for c in result.comments if c.severity == "warning")
    actual_suggestions = sum(1 for c in result.comments if c.severity == "suggestion")
    actual_praise = sum(1 for c in result.comments if c.severity == "praise")

    # Check if counts need correction
    needs_correction = (
        result.summary.critical_issues != actual_critical
        or result.summary.warnings != actual_warnings
        or result.summary.suggestions != actual_suggestions
        or result.summary.praise_count != actual_praise
    )

    # Correct counts if needed
    if needs_correction:
        logger.warning(
            f"Review result counts were incorrect. "
            f"Correcting: critical {result.summary.critical_issues}->{actual_critical}, "
            f"warnings {result.summary.warnings}->{actual_warnings}, "
            f"suggestions {result.summary.suggestions}->{actual_suggestions}, "
            f"praise {result.summary.praise_count}->{actual_praise}"
        )

        # Update summary with correct counts
        result.summary.critical_issues = actual_critical
        result.summary.warnings = actual_warnings
        result.summary.suggestions = actual_suggestions
        result.summary.praise_count = actual_praise

    # Log review completion
    logger.info(
        f"Code review completed for PR #{pr_number} in {repo_full_name}: "
        f"{result.total_comments} comments "
        f"({actual_critical} critical, {actual_warnings} warnings, "
        f"{actual_suggestions} suggestions, {actual_praise} praise), "
        f"{result.summary.files_reviewed} files reviewed, "
        f"recommendation: {result.summary.recommendation}"
    )

    return result
