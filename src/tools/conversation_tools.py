"""Code suggestion tools for conversation and review agents."""

import logging

from pydantic_ai import RunContext

from src.models.dependencies import ConversationDependencies, ReviewDependencies
from src.services.rag_service import rag_service

logger = logging.getLogger(__name__)

# Union type for shared tools
DepType = ConversationDependencies | ReviewDependencies


async def suggest_code_fix(
    ctx: RunContext[DepType],
    explanation: str,
    new_code: str,
    issue_category: str,
    file_path: str | None = None,
) -> str:
    # Validate inputs
    if not new_code or not new_code.strip():
        logger.error("suggest_code_fix called with empty new_code")
        return "Error: Cannot generate suggestion for empty code."

    if not explanation or not explanation.strip():
        logger.error("suggest_code_fix called with empty explanation")
        return "Error: Cannot generate suggestion without explanation."

    # Detect language from file path
    language = _detect_language(file_path) if file_path else None
    logger.info(
        f"Formatting code fix suggestion: category={issue_category}, language={language}"
    )

    # Get style guide context from RAG (for citation only)
    style_guide_context = await _get_style_guide_context(issue_category, language)

    # Format as GitHub suggestion
    suggestion_markdown = _format_as_github_suggestion(
        new_code=new_code,
        explanation=explanation,
        style_guide_context=style_guide_context,
    )

    logger.info(f"Successfully formatted code suggestion ({len(new_code)} chars)")
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
