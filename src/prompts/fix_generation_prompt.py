"""Prompt for LLM-based code fix generation."""


def get_fix_generation_prompt(
    old_code: str,
    explanation: str,
    issue_category: str,
    style_guide_context: str | None,
    language: str | None,
) -> str:
    """
    Generate a prompt for the LLM to fix code issues.

    Args:
        old_code: Original code with the issue
        explanation: Description of the issue
        issue_category: Type of issue (naming, type_hint, security, bug, etc.)
        style_guide_context: RAG-retrieved style guide excerpts (optional)
        language: Programming language (optional)

    Returns:
        Formatted prompt string for LLM
    """
    lang_hint = f" ({language})" if language else ""

    # Build style guide section if available
    style_guide_section = ""
    if style_guide_context:
        style_guide_section = f"""
Relevant style guide context:
{style_guide_context}
"""

    prompt = f"""You are a code quality expert. Fix the following code issue{lang_hint}.

Issue: {explanation}
Category: {issue_category}
{style_guide_section}
Original code:
```
{old_code}
```

Instructions:
1. Generate ONLY the corrected code
2. Do NOT include explanations, comments, or markdown
3. Preserve the original indentation and formatting style
4. Only change what's necessary to fix the issue
5. Ensure the fix follows the style guide context if provided

Output the corrected code exactly as it should appear in the file:"""

    return prompt
