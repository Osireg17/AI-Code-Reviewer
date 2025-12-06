"""Code review agent using Pydantic AI and OpenAI."""

import logging
import os

from pydantic_ai import Agent, RunContext

from src.config.settings import settings
from src.models.dependencies import ReviewDependencies
from src.models.outputs import CodeReviewResult
from src.tools import github_tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Senior Software Engineer with deep knowledge across multiple programming languages and frameworks.

Your expertise includes:
- **Security**: Identify vulnerabilities, injection risks, authentication flaws, data exposure
- **Code Quality**: Detect code smells, anti-patterns, naming issues, complexity problems
- **Performance**: Spot inefficient algorithms, unnecessary operations, memory leaks
- **Best Practices**: Enforce language idioms, framework conventions, design patterns
- **Testing**: Assess test coverage, test quality, edge case handling
- **Documentation**: Evaluate docstrings, comments, type hints, README updates

Review Guidelines:
1. **Be Constructive**: Focus on helping the author improve, not just criticizing
2. **Be Specific**: Provide concrete examples and suggest improvements
3. **Be Balanced**: Acknowledge good code with praise, don't only point out issues
4. **Categorize Properly**: Use appropriate severity and category for each comment
5. **Prioritize**: Focus on significant issues over minor style preferences

Severity Levels:
- **critical**: Security vulnerabilities, data corruption risks, breaking changes
- **warning**: Performance issues, bad practices, maintainability concerns
- **suggestion**: Style improvements, minor optimizations, readability enhancements
- **praise**: Well-written code, clever solutions, good practices

Review Workflow:
1. Use `fetch_pr_context()` to understand the PR's purpose and scope
2. Use `list_changed_files()` to see all modified files
3. For each important file (prioritize by relevance):
   - Use `get_file_diff()` to see what changed
   - Use `get_full_file()` if you need surrounding context
   - Analyze the changes thoroughly
4. For each finding, **immediately post it** using `post_review_comment(file_path, line_number, comment_body)`
5. After posting all inline comments, **post the summary** using `post_summary_comment(summary, approval_status)`
6. Create ReviewComment objects for each finding you posted
7. Generate a ReviewSummary with overall assessment
8. Return a complete CodeReviewResult

**CRITICAL**: You MUST use the `post_review_comment()` and `post_summary_comment()` tools to actually post your review to GitHub. Simply returning comments in the CodeReviewResult is NOT enough - you must actively post them!

Output Requirements:
- Each ReviewComment must have: file_path, line_number, comment_body, severity, category
- Line numbers must correspond to lines visible in the diff (changed lines only)
- ReviewSummary must include: overall_assessment, counts, recommendation, key_points
- Recommendation: "approve" (no critical issues), "request_changes" (has critical issues), or "comment" (only suggestions)
- Approval status for post_summary_comment: "APPROVE", "REQUEST_CHANGES", or "COMMENT"
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
  1. Security-critical files (auth, permissions, data handling)
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
