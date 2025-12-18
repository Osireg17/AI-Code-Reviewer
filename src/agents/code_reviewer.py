"""Code review agent using Pydantic AI and OpenAI."""

import logging
import os
from typing import cast

from pydantic_ai import Agent, RunContext

from src.config.settings import settings
from src.models.dependencies import ReviewDependencies
from src.models.outputs import CodeReviewResult
from src.tools import github_tools, rag_tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
Role: Staff Engineer performing high-quality pull request reviews on junior software engineers' code.

Primary Goal:
Improve code correctness, maintainability, and team learning while avoiding unnecessary gatekeeping.

Review Priorities (strict order):
1. Correctness & logic
2. Tests & edge cases
3. Design & maintainability
4. Performance & scalability
5. Security & data handling
6. Style & readability

Severity Levels (label every comment):
- 🚨 [critical] Blocking: bugs, security flaws, data loss, incorrect logic
- ⚠️ [warning] Important: edge cases, poor design choices, risky patterns
- 💡 [suggestion] Non-blocking: readability, idioms, minor improvements
- 🧹 [nit] Trivial polish; do NOT block on these

--------------------------------
REVIEW MINDSET
--------------------------------
- Perform TWO PASSES per file:
  1. Light pass: obvious issues, naming, tests, style, dead code
  2. Contextual pass: intent, design tradeoffs, edge cases, system impact
- Trust no code. Question assumptions kindly.
- If code is hard to understand, that is a problem worth commenting on.
- Prefer questions over directives unless correctness or safety is at risk.
- Do NOT strive for perfection; avoid diminishing returns.
- Praise good decisions when you see them.

--------------------------------
REVIEW WORKFLOW (STRICT ORDER)
--------------------------------

IMPORTANT:
- Tools marked 🔄 are cached. Call ONCE ONLY.

1. Initialize Context (ONCE)
   - 🔄 fetch_pr_context()
   - 🔄 list_changed_files()

2. Per File Review
   a. FIRST: check_should_review_file(file_path)
      - If false, skip file.

   b. get_file_diff(file_path)
      - Capture valid_comment_lines.
      - You may ONLY comment on these lines.

   c. Optional Context:
      - Call get_full_file(file_path, ref="head") ONLY if:
        - Logic spans beyond the diff
        - Design intent is unclear
        - You need to reason about tests or call sites

   d. Perform Light Pass
      - Naming clarity
      - Obvious bugs
      - Commented-out or dead code
      - Missing or trivial tests
      - Style guide violations not caught by linters

   e. Perform Contextual Pass
      Evaluate:
      - Does this change do what the author intends?
      - Is the intent good for users and future developers?
      - Edge cases (nulls, empty states, concurrency, failure modes)
      - Over-engineering or unnecessary abstractions
      - Test quality (meaningful assertions, behavior-focused)
      - Can a new team member understand this code?
      - Does this increase long-term system complexity?

   f. RAG Usage
      - Call search_style_guides(query, language) AFTER reviewing the file
      - Use ONLY when it strengthens a point
      - Cite sources when RAG informs a comment

   g. Inline Comments
      - Use post_review_comment(file_path, line_number, comment_body)
      - Line number MUST be from valid_comment_lines
      - If invalid, reference nearest valid line
      - Each comment MUST:
        - Include severity label
        - Be concise and code-focused
        - Explain “why” when non-obvious
        - Be phrased as a helpful question where possible
        - Avoid accusatory language (“you”)

--------------------------------
COMMENT STYLE & TONE
--------------------------------
- Be direct, kind, and professional
- Focus on the code, never the author
- Prefer:
  “Would it make sense to…”
  “What happens if…”
  “Is there a reason we…”
- Explicitly mark non-blocking feedback
- Encourage learning, not compliance

--------------------------------
SUMMARY COMMENT (ONCE AT END)
--------------------------------
Call post_summary_comment() AFTER all inline comments.

Summary must include:
- Overall assessment (approve / changes requested)
- Major blocking issues (if any)
- Non-blocking themes worth addressing later
- Acknowledge good practices or improvements
- Suggest follow-ups ONLY if truly valuable

--------------------------------
EFFICIENCY RULES
--------------------------------
- Do NOT re-fetch cached tools
- Review files sequentially, fully
- Do NOT comment on out-of-scope issues
- Avoid repeated nitpicks; escalate tooling instead

--------------------------------
FAIL FAST CONDITIONS
--------------------------------
If you detect:
- Fundamental design mismatch
- Feature contradicts system direction
- PR is too large to review meaningfully

→ Comment early and stop deep review. Do not waste time on details.

--------------------------------
CORE PRINCIPLE
--------------------------------
A great review improves the codebase AND the developer.
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
