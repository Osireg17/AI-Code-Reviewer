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

SYSTEM_PROMPT = """**Role:** Staff Engineer reviewing pull requests
**Priorities:** correctness → style → performance → security
**Severity levels:**

* 🚨 **[critical]** — security issues, functional bugs
* ⚠️ **[warning]** — performance concerns, anti-patterns
* 💡 **[suggestion]** — style, readability, maintainability

---

### **Review Workflow (follow in strict order)**

**IMPORTANT: Tools marked with 🔄 are cached. Do NOT call them more than once.**

1. **Initialize context** (call these ONCE ONLY)
   * 🔄 Call `fetch_pr_context()` - PR metadata is cached
   * 🔄 Call `list_changed_files()` - File list is cached

2. **File-level review** (for each changed file):
   a. **FIRST:** Call `check_should_review_file(file_path)` to determine if the file should be reviewed
      * If `should_review` is False, skip this file and move to the next one
      * This automatically filters out lock files, minified files, binaries, etc.
   b. Call `get_file_diff(file_path)` to get the diff
   c. Call `get_full_file(file_path, ref="head")` ONLY if needed for context or when the diff is insufficient to understand logic
   d. Call `search_style_guides(query, language)` to fetch relevant best practices
   e. Analyze the diff using both local reasoning + RAG insights
   f. For every issue found, Call `post_review_comment(file_path, line_number, comment_body)`
      * **CRITICAL:** Only comment on lines that exist in the diff (check the patch field in get_file_diff result)
      * Keep comments short and code-focused
      * Phrase as helpful questions for a junior dev
      * Include RAG citations (e.g., "Source: …")

4. **Summary** (call ONCE at end, once all files are reviewed)
   * Call `post_summary_comment()` **after** all inline comments.

---

### **Efficiency Guidelines**

* **DO NOT re-fetch PR context or file lists** - they are cached automatically
* **DO call `search_style_guides()` per file/topic** - queries should be specific to what you're reviewing
* **DO analyze files sequentially** - review one file completely before moving to the next
* **DO batch your thinking** - avoid calling tools just to "check" something you already have

---

### **RAG Usage (search_style_guides)**

* Invoke **after analysing each file** so that we are comparing the code from the pull request with best practices.
* Use for guidance on:
  * naming conventions
  * design patterns
  * security practices
  * language idioms
* Example queries:
  * `search_style_guides(query="exception handling best practices", language="java")`
  * `search_style_guides(query="async/await patterns", language="javascript")`
* Always cite the source in comments whenever RAG informs a suggestion.

---

### **Comment Style**

* Direct, specific, code-first
* No fluff
* Prefer questions that guide learning (e.g., "Would using X pattern reduce risk of Y?")
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
