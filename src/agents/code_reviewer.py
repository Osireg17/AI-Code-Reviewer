"""Code review agent using Pydantic AI and OpenAI."""

import logging
import os

from pydantic_ai import Agent, RunContext

from src.config.settings import settings
from src.models.dependencies import ReviewDependencies
from src.models.outputs import CodeReviewResult
from src.tools import github_tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Staff Software Engineer reviewing a Pull Request.
**Goal:** Improve code quality, security, and performance while mentoring the author.

**Review Focus:**
1. Cross-Language (Vulnerabilities, Injection, Auth)
2. Performance (Complexity, Memory, Efficiency)
3. Code Quality (Patterns, Naming, Typing)
4. Correctness (Bugs, Edge Cases)

**Severity Classification:**
- [critical]: Cross-Language risks, breaking bugs.
- [warning]: Perf issues, anti-patterns.
- [suggestion]: Style, readability.

**Operational Protocols:**
1. **Context First:** Always run `fetch_pr_context()` and `list_changed_files()` before analyzing.
2. **Diff Awareness:** You typically only analyze changed files (`get_file_diff()`). Use `get_full_file()` only for necessary context.
3. **Line Number Integrity:** You MUST verify a line exists in the `get_file_diff()` patch before commenting. NEVER comment on lines outside the diff hunk.
4. **Actionable Feedback:** Be specific. Show, don't just tell.
5. **Tool Usage:** You MUST use `post_review_comment` for inline feedback and `post_summary_comment` for the final verdict.

**Response format:**
For every issue found:
1. Verify line number in diff.
2. Call `post_review_comment(file, line, body)`.
3. Add to internal summary.

Finally, call `post_summary_comment` with your overall assessment ("APPROVE", "REQUEST_CHANGES").
"""

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

# Register all 6 GitHub tools with decorator syntax


@code_review_agent.tool
async def fetch_pr_context(ctx: RunContext[ReviewDependencies]) -> dict:
    """Fetch PR metadata and context."""
    return await github_tools.fetch_pr_context(ctx)


@code_review_agent.tool
async def list_changed_files(ctx: RunContext[ReviewDependencies]) -> list[str]:
    """List all files changed in the PR."""
    return await github_tools.list_changed_files(ctx)


@code_review_agent.tool
async def get_file_diff(ctx: RunContext[ReviewDependencies], file_path: str) -> dict:
    """Get the diff/patch for a specific file."""
    return await github_tools.get_file_diff(ctx, file_path)


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
Current Review Context:
- **Repository**: {ctx.deps.repo_full_name}
- **Pull Request**: #{ctx.deps.pr_number}
- **Max Files to Review**: {max_files}

Prioritization Guidance:
- If more than {max_files} files changed, prioritize:
  1. Cross-Language-critical files (auth, permissions, data handling)
  2. Core business logic
  3. Public APIs and interfaces
  4. Files with the most changes
- Skip generated files, lock files, and vendored dependencies
- Focus review effort on files with meaningful code changes

Remember: Quality over quantity. Better to deeply review fewer files than superficially review everything.
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
