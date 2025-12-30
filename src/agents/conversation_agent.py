import logging
import os

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIResponsesModel

from src.config.settings import settings
from src.models.dependencies import ConversationDependencies
from src.prompts.conversation_agent_prompt import SYSTEM_PROMPT
from src.services.rag_service import rag_service
from src.tools import conversation_tools

logger = logging.getLogger(__name__)

# Set OpenAI API key as environment variable for Pydantic AI
if settings.openai_api_key:
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key

# Future Extension (Statefulness):
#   To enable stateful conversations with previous_response_id:
#   1. Create model_settings = OpenAIResponsesModelSettings(store=True)
responses_model = OpenAIResponsesModel(settings.openai_model)
#   3. Pass previous_response_id from result.all_messages()[-1].provider_response_id
#   4. Benefits: Model remembers context across turns without resending full history
#   5. Example in Pydantic AI docs: https://ai.pydantic.dev/models/openai/#referencing-earlier-responses
responses_model = OpenAIResponsesModel("gpt-5")

conversation_agent = Agent[ConversationDependencies, str](
    model=responses_model,
    instructions=SYSTEM_PROMPT,
    deps_type=ConversationDependencies,
)


@conversation_agent.tool
async def search_coding_standards(
    ctx: RunContext[ConversationDependencies], query: str, language: str
) -> str:
    """
    Search coding style guides for authoritative guidance.

    Use this tool when you need to cite official coding standards or best practices
    to support your explanation.

    Args:
        query: Search query (e.g., "error handling", "naming conventions")
        language: Programming language (e.g., "python", "javascript", "typescript")

    Returns:
        Formatted string with relevant style guide excerpts and citations
    """
    if not rag_service.is_available():
        return "Unable to search coding standards at this time."

    results = await rag_service.search_style_guides(
        query=query, language=language, top_k=3
    )
    return str(results)


@conversation_agent.tool
def get_code_context(
    ctx: RunContext[ConversationDependencies],
    use_current: bool = True,
    context_lines: int = 5,
) -> str:
    """
    Get code snippet with surrounding context.

    Use this tool when you need to reference the specific code being discussed.

    Args:
        use_current: If True, show current code; if False, show original code
        context_lines: Number of lines before/after to include (default: 5)

    Returns:
        Formatted code snippet with line numbers
    """
    deps = ctx.deps

    if use_current and deps.current_code_snippet:
        code = deps.current_code_snippet
    elif not use_current and deps.original_code_snippet:
        code = deps.original_code_snippet
    else:
        return "[Code not available - file may have been deleted or moved]"

    return f"```\n{code}\n```"


@conversation_agent.tool
def check_code_changes(ctx: RunContext[ConversationDependencies]) -> str:
    """
    Check if code has changed since original review.

    Use this tool when you want to see if the developer has updated the code
    since your original comment.

    Returns:
        String describing what changed or if code is the same
    """
    deps = ctx.deps

    if not deps.code_changed:
        return "Code appears unchanged since the original review."

    if not deps.original_code_snippet or not deps.current_code_snippet:
        return "Code has been modified, but details are not available."

    return f"""Code has been updated since the original review.

**Original code:**
```
{deps.original_code_snippet}
```

**Current code:**
```
{deps.current_code_snippet}
```
"""


@conversation_agent.tool
async def suggest_code_fix(
    ctx: RunContext[ConversationDependencies],
    explanation: str,
    new_code: str,
    issue_category: str,
) -> str:
    """
    Format a code fix as GitHub's suggestion markdown with "Commit suggestion" button.

    Use this tool when the developer asks "how do I fix this?" or requests
    implementation help. You (the agent) should generate the corrected code,
    then call this tool to format it as a GitHub suggestion.

    Args:
        explanation: Description of the issue (e.g., "Parameter should be 'exc_string' not 'traceback'")
        new_code: The corrected code you've generated (e.g., "return SimpleNamespace(return_value=self.return_value, exc_string=None)")
        issue_category: Type of issue (e.g., "naming", "type_hint", "security", "bug", "consistency")

    Returns:
        Formatted GitHub suggestion markdown with citation (if RAG finds relevant style guide)

    Example usage:
        User: "How should I fix this parameter name issue?"
        Agent reasoning: The parameter should be 'exc_string' not 'traceback' based on line 68
        -> Call suggest_code_fix(
            explanation="Parameter should be 'exc_string' to match endpoint implementation",
            new_code="return SimpleNamespace(return_value=self.return_value, exc_string=None)",
            issue_category="consistency"
        )

    Output: GitHub will render this as an inline suggestion with "Commit suggestion" button
    """
    # Get file_path from dependencies for language detection
    file_path = ctx.deps.file_path

    return await conversation_tools.suggest_code_fix(
        ctx=ctx,
        explanation=explanation,
        new_code=new_code,
        issue_category=issue_category,
        file_path=file_path,
    )


def validate_conversation_response(response: str) -> str:
    """
    Validate and sanitize agent response before posting to GitHub.

    Args:
        response: Raw agent response string

    Returns:
        Validated and sanitized response ready for GitHub

    Raises:
        None - always returns a safe string
    """
    if not response or not response.strip():
        logger.warning("Agent returned empty response")
        return "I encountered an issue generating a response. Could you rephrase your question?"

    cleaned_response = response.strip()

    max_length = 2000
    if len(cleaned_response) > max_length:
        logger.warning(
            f"Response too long ({len(cleaned_response)} chars), truncating to {max_length}"
        )
        cleaned_response = cleaned_response[:max_length].rsplit(" ", 1)[0]
        cleaned_response += "\n\n[Response truncated due to length...]"

    return cleaned_response
