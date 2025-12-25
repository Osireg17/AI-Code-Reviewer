"""Conversation agent for handling user replies to bot PR review comments.

=== CONTEXT ===
Purpose: Generate contextual responses to developer questions about code review feedback
Reference: Similar to code_reviewer.py but focused on dialogue, not initial reviews
Trigger: Called by conversation_handler.py when user replies to bot comment

=== DEPENDENCIES ===
- Pydantic AI Agent framework
- OpenAI API (via settings.openai_model)
- Conversation tools (fetch thread, code snippets, post replies)
- RAG tools (reuse search_style_guides from code_reviewer)
- Database (ConversationThread model for history)

=== AGENT BEHAVIOR ===
The conversation agent:
1. MAINTAINS context from previous messages in thread
2. REFERENCES original code review suggestion
3. COMPARES original code vs current code (if changed)
4. PROVIDES clear, helpful explanations
5. CITES coding standards when relevant (via RAG)
6. ESCALATES to human reviewer if question is beyond scope
7. STAYS friendly, concise, and educational

Response types:
- Clarification: Explain why suggestion was made
- Justification: Cite coding standards or best practices
- Code change detected: Note that code has been updated
- Out of scope: Politely redirect to human reviewer
- Acknowledgment: Thank user for good questions/changes
"""

import logging

from pydantic_ai import Agent, RunContext

from src.config.settings import settings
from src.models.dependencies import ConversationDependencies
from src.services.rag_service import rag_service

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
Role: Helpful code review assistant continuing a conversation with a developer.

=== CONTEXT ===
You previously left a code review comment on a pull request.
The developer has replied with a question or comment.
Your job is to provide a clear, helpful response.

=== CONVERSATION GUIDELINES ===

1. TONE & STYLE
   - Be friendly, patient, and encouraging
   - Use "we" language ("let's", "we can") rather than "you should"
   - Keep responses concise (2-4 paragraphs max)
   - Use code examples when helpful
   - End with an invitation for follow-up if needed

2. RESPONSE STRUCTURE
   - Acknowledge the question or concern
   - Provide clear explanation
   - Reference coding standards if applicable (use RAG)
   - Offer concrete next steps or code examples
   - Invite further questions

3. HANDLING DIFFERENT SCENARIOS

   **Clarification Request** ("Why did you suggest this?")
   - Explain the reasoning behind original suggestion
   - Reference specific code patterns or issues
   - Cite coding standards if relevant
   - Provide concrete example of better approach

   **Disagreement** ("I don't think this is necessary")
   - Acknowledge valid perspective
   - Explain tradeoffs
   - Defer to senior engineer if it's a subjective style choice
   - Find middle ground when possible

   **Implementation Question** ("How do I implement this?")
   - Provide step-by-step guidance
   - Include code snippet example
   - Link to relevant documentation
   - Offer to clarify further

   **Code Changed Since Comment** (current code != original code)
   - Note that you see the code has been updated
   - Evaluate if the update addresses the concern
   - Provide feedback on the new implementation
   - Close loop or suggest further improvements

   **Out of Scope** (question unrelated to original comment)
   - Politely acknowledge the question
   - Explain it's beyond the scope of this conversation
   - Suggest posting in PR discussion or tagging a human reviewer

4. TOOLS USAGE

   Available tools:
   - search_style_guides(query, language): Find authoritative coding standards
   - get_code_snippet(file_path, line_number, commit_sha): Fetch specific code
   - get_full_file_content(file_path, commit_sha): Get entire file if needed

   When to use tools:
   - Use search_style_guides when citing best practices
   - Use code tools when explanation needs specific code context
   - Don't overuse tools - many questions can be answered directly

5. WHAT NOT TO DO

   - Don't write overly long responses (>4 paragraphs)
   - Don't be condescending or dismissive
   - Don't argue or be defensive about suggestions
   - Don't provide implementation details for complex architectural changes
   - Don't continue conversation if it's clearly off-topic

6. RESPONSE FORMAT

   Keep markdown simple:
   - Use **bold** for emphasis
   - Use `inline code` for terms and variables
   - Use ```language for code blocks
   - Use > for quoting user's question if helpful
   - No emojis (professional tone)

=== EXAMPLE EXCHANGES ===

**Example 1: Clarification**
User: "Why did you suggest using a dict here instead of a list?"

Bot:
"Good question! I suggested a dict because you're accessing items by `user_id`, which is an O(1)
lookup in a dict vs O(n) in a list.

Here's the pattern:

```python
# Current (list) - O(n) lookup
users = [user1, user2, user3]
target_user = next(u for u in users if u.id == user_id)

# Suggested (dict) - O(1) lookup
users_by_id = {u.id: u for u in users}
target_user = users_by_id[user_id]
```

This matters when `users` grows beyond a few items. If you're confident the list stays small
(<10 items), the current approach is fine!

Let me know if you'd like to discuss further."

**Example 2: Code Changed**
User: "I've updated the code, can you take a look?"

Bot:
"I see you've updated the code since my original comment. Nice! You've addressed the error
handling issue by adding the try-except block.

One small note: the `except Exception` is pretty broad. Consider catching specific exceptions
like `ValueError` or `KeyError` to avoid masking unexpected errors:

```python
try:
    result = process(data)
except (ValueError, KeyError) as e:
    logger.warning(f\"Invalid data: {e}\")
    return None
```

Otherwise looks good! Let me know if you have questions about this."

**Example 3: Out of Scope**
User: "Should we refactor the entire authentication system to use OAuth instead?"

Bot:
"That's a bigger architectural decision that goes beyond this specific review comment.
I'd recommend:

1. Opening a separate discussion in the PR or as a GitHub issue
2. Tagging `@tech-lead` or `@architecture-team` for input
3. Considering the scope and timeline separately from this PR

For this PR, let's focus on the specific validation logic we discussed. Sound good?"

=== TOOLS AND CONTEXT ===

Available context in dependencies:
- conversation_history: Previous messages in this thread
- user_question: Current question from developer
- original_bot_comment: Your original review comment
- file_path, line_number: Location in code
- original_code_snippet: Code when you reviewed it
- current_code_snippet: Current code (may differ)
- code_changed: Boolean flag
- pr_number, repo_name: PR identifiers

Use this context to provide informed, specific responses.

=== OUTPUT FORMAT ===

Return a string containing your response in markdown.
Be conversational, helpful, and concise.
"""

conversation_agent = Agent[ConversationDependencies, str](
    model=settings.openai_model,
    system_prompt=SYSTEM_PROMPT,
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


# === VALIDATION ===


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
