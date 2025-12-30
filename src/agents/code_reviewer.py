"""Code review agent using Pydantic AI and OpenAI."""

import logging
import os
from typing import cast

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIResponsesModel

from src.config.settings import settings
from src.models.dependencies import ReviewDependencies
from src.models.outputs import CodeReviewResult
from src.prompts.code_reviewer_prompt import SYSTEM_PROMPT
from src.tools import conversation_tools, github_tools, rag_tools

logger = logging.getLogger(__name__)


# Set OpenAI API key as environment variable for Pydantic AI
if settings.openai_api_key:
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key

# Future Extension (Statefulness):
#   To enable stateful multi-file reviews with previous_response_id:
#   1. Create model_settings = OpenAIResponsesModelSettings(store=True)
#   2. Pass model_settings to Agent constructor
#   3. Pass previous_response_id from previous file review to next file
#   4. Benefits: Agent remembers context across files in same PR review
#   5. Example: Review file 1 → get response_id → pass to file 2 review
responses_model = OpenAIResponsesModel("gpt-5")

# Create the code review agent
code_review_agent = Agent(
    model=responses_model,
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

    Use this tool to provide ready-to-commit fixes for bugs, security issues, code
    improvements, and convention violations. Helps developers move faster by allowing
    them to commit fixes directly from GitHub without switching to their IDE.

    You (the agent) must generate the corrected code using your reasoning, then call
    this tool to format it as a GitHub suggestion with optional RAG-backed citations.

    Args:
        explanation: Clear description of the issue and why the fix is needed
        new_code: The corrected code (single or multiple lines with proper indentation)
        issue_category: Type of issue - one of: "bug", "security", "naming", "type_hint",
                       "import", "improvement", "performance", "best_practice", "formatting"
        file_path: Path to the file being reviewed (e.g., "src/main.py") - used for language detection

    Returns:
        Formatted GitHub suggestion markdown with optional RAG citation

    When to use (broad scope):
        ✅ Bug fixes (null checks, off-by-one errors, logic bugs)
        ✅ Security issues (SQL injection, XSS, hardcoded secrets)
        ✅ Naming convention violations
        ✅ Type hints (missing or incorrect)
        ✅ Import issues (ordering, unused, missing)
        ✅ Code improvements (better idioms, simplified logic)
        ✅ Performance issues (obvious inefficiencies)
        ✅ Best practices (context managers, early returns)
        ✅ Formatting & style (quotes, spacing, line length)

    When NOT to use:
        ❌ Architectural changes across multiple files
        ❌ Business logic you don't fully understand
        ❌ Changes requiring broader system context
        ❌ Subjective preferences without style guide backing

    Example usage (bug fix):
        File: src/handlers.py
        Original: if user: process(user.name)
        Issue: Missing null check for user.name
        -> Call suggest_code_fix(
            explanation="Missing check for user.name attribute. This will raise AttributeError if name is None.",
            new_code="if user and user.name:\n    process(user.name)",
            issue_category="bug",
            file_path="src/handlers.py"
        )

    Example usage (security fix):
        File: src/database.py
        Original: query = f"SELECT * FROM users WHERE id = {user_id}"
        Issue: SQL injection vulnerability
        -> Call suggest_code_fix(
            explanation="SQL injection vulnerability. User input should be parameterized.",
            new_code='query = "SELECT * FROM users WHERE id = ?"',
            issue_category="security",
            file_path="src/database.py"
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
