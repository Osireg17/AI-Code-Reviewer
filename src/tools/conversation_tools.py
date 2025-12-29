"""Code suggestion tools for conversation and review agents."""

import logging

from pydantic_ai import RunContext

from src.models.dependencies import ConversationDependencies, ReviewDependencies
from src.prompts.fix_generation_prompt import get_fix_generation_prompt
from src.services.rag_service import rag_service

logger = logging.getLogger(__name__)

# Union type for shared tools
DepType = ConversationDependencies | ReviewDependencies


async def suggest_code_fix(
    ctx: RunContext[DepType],
    explanation: str,
    old_code: str,
    issue_category: str,
    file_path: str | None = None,
) -> str:
    """
    Generate and format a code fix suggestion.

    === CONTEXT ===
    Purpose: Create GitHub-formatted code suggestions with RAG-enhanced context
    Used by: conversation_agent and code_review_agent
    Reference: GitHub suggestion syntax - https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/commenting-on-a-pull-request#adding-line-comments-to-a-pull-request

    === BEHAVIOR ===

    Input:
    - explanation: Description of the issue (e.g., "Variable should use snake_case")
    - old_code: Original code snippet with the issue
    - issue_category: Type of issue ("naming", "type_hint", "security", "bug", etc.)
    - file_path: Optional file path for language detection

    Output:
    - Formatted markdown string with GitHub suggestion syntax

    Logic Flow:
    1. DETECT language from file_path if provided
    2. SEARCH RAG for relevant style guide context using issue_category
    3. GENERATE fix using LLM with style guide context
    4. VALIDATE new code differs from old code
    5. FORMAT as GitHub suggestion markdown
    6. RETURN formatted suggestion

    Edge Cases:
    - RAG unavailable: Generate fix without style guide context
    - LLM fails: Return error message
    - Generated code identical to original: Log warning, return anyway
    - Empty old_code: Return error message

    === INTEGRATION ===
    Triggered by: Agent tool call when developer asks for fix
    Calls into: RAG service, OpenAI API (via agent context)
    Error handling: Log errors, return user-friendly message

    Args:
        ctx: Run context with dependencies (ConversationDependencies or ReviewDependencies)
        explanation: Description of the issue to fix
        old_code: Original code with the issue
        issue_category: Category of issue (naming, type_hint, security, bug, etc.)
        file_path: Optional file path for language detection

    Returns:
        Formatted GitHub suggestion markdown string
    """
    # Validate inputs
    if not old_code or not old_code.strip():
        logger.error("suggest_code_fix called with empty old_code")
        return "Error: Cannot generate suggestion for empty code."

    if not explanation or not explanation.strip():
        logger.error("suggest_code_fix called with empty explanation")
        return "Error: Cannot generate suggestion without explanation."

    # Detect language from file path
    language = _detect_language(file_path) if file_path else None
    logger.info(
        f"Generating code fix suggestion: category={issue_category}, language={language}"
    )

    # Get style guide context from RAG
    style_guide_context = await _get_style_guide_context(issue_category, language)

    # Generate fix using LLM
    new_code = await _call_llm_for_fix(
        old_code=old_code,
        explanation=explanation,
        issue_category=issue_category,
        style_guide_context=style_guide_context,
        language=language,
    )

    if not new_code:
        logger.error("LLM failed to generate code fix")
        return "Error: Unable to generate code suggestion at this time."

    # Validate new code differs from old
    if new_code.strip() == old_code.strip():
        logger.warning(
            "Generated code is identical to original - LLM may not have understood the issue"
        )

    # Format as GitHub suggestion
    suggestion_markdown = _format_as_github_suggestion(
        new_code=new_code,
        explanation=explanation,
        style_guide_context=style_guide_context,
    )

    logger.info(f"Successfully generated code suggestion ({len(new_code)} chars)")
    return suggestion_markdown


async def _get_style_guide_context(
    issue_category: str, language: str | None
) -> str | None:
    """
    Search RAG for relevant style guide context.

    Args:
        issue_category: Type of issue (naming, type_hint, security, etc.)
        language: Programming language (python, javascript, etc.)

    Returns:
        Style guide excerpt text, or None if RAG unavailable
    """
    if not rag_service.is_available():
        logger.warning("RAG service unavailable, generating fix without style guide")
        return None

    try:
        # Search for relevant style guide content
        results = await rag_service.search_style_guides(
            query=f"{issue_category} best practices",
            language=language,
            top_k=2,  # Just need top 2 most relevant excerpts
        )

        if not results:
            logger.info(f"No style guide results found for {issue_category}")
            return None

        # Extract text from top results
        excerpts = []
        for result in results[:2]:
            text = result.get("text", "")
            source = result.get("source", "Style Guide")
            if text:
                excerpts.append(f"{source}: {text}")

        context = "\n\n".join(excerpts) if excerpts else None
        logger.info(f"Retrieved {len(excerpts)} style guide excerpts")
        return context

    except Exception as e:
        logger.error(f"Error fetching style guide context: {e}")
        return None


async def _call_llm_for_fix(
    old_code: str,
    explanation: str,
    issue_category: str,
    style_guide_context: str | None,
    language: str | None,
) -> str | None:
    """
    Call LLM to generate corrected code.

    === CONTEXT ===
    Purpose: Generate fixed code using LLM with style guide context
    Used by: suggest_code_fix()

    === BEHAVIOR ===
    Input:
    - old_code: Original code with issue
    - explanation: Description of the issue
    - issue_category: Type of issue
    - style_guide_context: RAG-retrieved style guide excerpts
    - language: Programming language

    Output:
    - Corrected code string, or None if generation fails

    Logic Flow:
    1. BUILD focused prompt with style guide context
    2. CALL OpenAI API to generate fix
    3. EXTRACT code from response
    4. PRESERVE original indentation
    5. RETURN corrected code

    Edge Cases:
    - No style guide context: Generate fix based on general knowledge
    - LLM returns explanation instead of code: Extract code block
    - LLM API error: Return None

    Args:
        old_code: Original code with issue
        explanation: Issue description
        issue_category: Issue category
        style_guide_context: Style guide excerpts from RAG
        language: Programming language

    Returns:
        Corrected code string, or None if generation fails
    """
    # Generate the prompt using the fix generation template
    prompt = get_fix_generation_prompt(
        old_code=old_code,
        explanation=explanation,
        issue_category=issue_category,
        style_guide_context=style_guide_context,
        language=language,
    )

    # TODO: Implement actual LLM call using OpenAI client
    # This is a placeholder that will be implemented with proper OpenAI API integration
    logger.warning(
        "_call_llm_for_fix prompt generated but LLM call not yet implemented"
    )
    logger.debug(f"Generated prompt:\n{prompt}")

    # Placeholder: return old_code with a comment (will be replaced with actual LLM call)
    return f"# TODO: Fix {issue_category}\n{old_code}"


def _format_as_github_suggestion(
    new_code: str, explanation: str, style_guide_context: str | None
) -> str:
    """
    Format corrected code as GitHub suggestion markdown.

    GitHub suggestion syntax:
    ```suggestion
    corrected_code_here
    ```

    Args:
        new_code: Corrected code
        explanation: Issue description
        style_guide_context: Style guide context (for citation)

    Returns:
        Formatted markdown string
    """
    # Extract citation from style guide context if available
    citation = ""
    if style_guide_context:
        # Extract first source reference from style guide context
        lines = style_guide_context.split("\n")
        if lines:
            first_line = lines[0]
            # Extract source (e.g., "PEP 8: ..." -> "PEP 8")
            if ":" in first_line:
                source = first_line.split(":")[0].strip()
                citation = f"as per {source}"

    # Build suggestion comment
    parts = []

    # Add explanation with citation if available
    if citation:
        parts.append(f"{explanation} ({citation}):")
    else:
        parts.append(f"{explanation}:")

    parts.append("")  # Blank line

    # Add GitHub suggestion block
    parts.append("```suggestion")
    parts.append(new_code)
    parts.append("```")

    return "\n".join(parts)


def _detect_language(file_path: str | None) -> str | None:
    """
    Detect programming language from file path.

    Args:
        file_path: Path to file (e.g., "src/main.py")

    Returns:
        Language name (python, javascript, java, etc.) or None
    """
    if not file_path:
        return None

    # Map file extensions to language names
    extension_map = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".rb": "ruby",
        ".php": "php",
        ".cpp": "cpp",
        ".c": "c",
        ".cs": "csharp",
        ".swift": "swift",
        ".kt": "kotlin",
    }

    # Extract extension
    for ext, lang in extension_map.items():
        if file_path.endswith(ext):
            return lang

    return None
