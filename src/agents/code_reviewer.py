"""Code review agent using Pydantic AI and OpenAI."""

# TODO: Import logging
# TODO: Import Agent and RunContext from pydantic_ai
# TODO: Import settings from src.config
# TODO: Import ReviewDependencies and CodeReviewResult from src.models
# TODO: Import github_tools from src.tools

# TODO: Create logger

# TODO: Define SYSTEM_PROMPT string with:
#   - Role description (expert code reviewer)
#   - Review focus areas (security, code quality, performance, best practices, testing, documentation)
#   - Review guidelines (be constructive, specific, balance criticism with praise)
#   - Severity levels (critical, warning, suggestion, praise)
#   - Output format instructions (use tools, analyze files, create comments, provide summary)

# TODO: Create code_review_agent instance:
#   - Model: f"openai:{settings.openai_model}"
#   - deps_type=ReviewDependencies
#   - result_type=CodeReviewResult
#   - system_prompt=SYSTEM_PROMPT
#   - retries=settings.max_retries

# TODO: Register all 6 tools using @code_review_agent.tool decorator:
#   - github_tools.fetch_pr_context
#   - github_tools.list_changed_files
#   - github_tools.get_file_diff
#   - github_tools.get_full_file
#   - github_tools.post_review_comment
#   - github_tools.post_summary_comment

# TODO: Create @code_review_agent.system_prompt decorator function:
#   - async def add_dynamic_context(ctx: RunContext[ReviewDependencies]) -> str
#   - Return additional context with repo name, PR number, max files to review
#   - Provide guidance on prioritization

# TODO: Create @code_review_agent.result_validator decorator function:
#   - async def validate_review_result(ctx, result: CodeReviewResult) -> CodeReviewResult
#   - Count actual comments by severity
#   - Correct summary counts if they don't match
#   - Log warnings for corrections
#   - Log review completion
#   - Return result
