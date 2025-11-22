# AI Code Review Agent

Automated GitHub PR code review using Pydantic AI and OpenAI.

## Implementation Steps

- **Install dependencies**: Run `pip install -e ".[dev]"` from pyproject.toml
- **Create `.env` file**: Copy `.env.example` to `.env` and add your API keys (OpenAI API key, GitHub token, webhook secret)
- **Implement `src/models/dependencies.py`**: Create ReviewDependencies dataclass with validation in `__post_init__`
- **Implement `src/models/github_types.py`**: Create PRContext, FileDiff, and FileMetadata Pydantic models with helper properties
- **Implement `src/models/outputs.py`**: Create ReviewComment, ReviewSummary, and CodeReviewResult models with `format_summary_markdown()` method
- **Implement `src/config/settings.py`**: Create Settings class using Pydantic Settings for all environment variables
- **Implement `src/utils/logging.py`**: Create `setup_logging()` and `setup_observability()` functions for logging and Logfire
- **Implement `src/utils/filters.py`**: Define excluded patterns, code extensions, and implement `should_review_file()` and `prioritize_files()` functions
- **Implement `fetch_pr_context()` in `src/tools/github_tools.py`**: Get PR metadata from GitHub API and return PRContext
- **Implement `list_changed_files()` in `src/tools/github_tools.py`**: Return list of changed file paths
- **Implement `get_file_diff()` in `src/tools/github_tools.py`**: Get diff/patch for a specific file
- **Implement `get_full_file()` in `src/tools/github_tools.py`**: Fetch complete file content at specific git ref, handle binary files and errors
- **Implement `post_review_comment()` in `src/tools/github_tools.py`**: Post inline comment to specific line in PR
- **Implement `post_summary_comment()` in `src/tools/github_tools.py`**: Post overall review summary with approval status
- **Test GitHub tools manually**: Create a test PR in a personal repo and test each tool function with a Python script
- **Write system prompt in `src/agents/code_reviewer.py`**: Define agent role, focus areas, guidelines, and severity levels
- **Create agent instance in `src/agents/code_reviewer.py`**: Initialize Agent with OpenAI model, deps_type, result_type
- **Register all 6 tools to agent**: Use `@code_review_agent.tool` decorator for each GitHub tool function
- **Add dynamic context with `@system_prompt` decorator**: Inject PR-specific information into agent instructions
- **Add result validator with `@result_validator` decorator**: Verify and correct comment counts in summary
- **Implement `src/main.py`**: Create FastAPI app, add startup event for observability, add health check endpoint
- **Implement `src/api/webhooks.py`**: Create POST `/webhook/github` endpoint that handles PR events and runs the agent
- **Add webhook signature verification in `src/api/webhooks.py`**: Verify GitHub webhook secret for security
- **Implement `src/api/dependencies.py`**: Create FastAPI dependency injection functions for GitHub client
- **Test locally with uvicorn**: Run `uvicorn src.main:app --reload` and verify health endpoint works
- **Set up ngrok**: Run `ngrok http 8000` to expose local server for webhook testing
- **Configure GitHub webhook**: Add webhook in test repo settings with ngrok URL
- **Create test PR**: Open a PR in test repo and verify agent reviews it
- **Implement `tests/conftest.py`**: Create pytest fixtures for mock GitHub client, TestModel, and ReviewDependencies
- **Write tests in `tests/unit/test_tools/test_github_tools.py`**: Test each tool function with mocked GitHub API
- **Write tests in `tests/unit/test_agents/test_code_reviewer.py`**: Test agent with TestModel, verify tool calls and validation
- **Write tests in `tests/integration/test_api/test_webhooks.py`**: Test webhook endpoint with mock payload
- **Run test suite**: Execute `pytest` to ensure all tests pass
- **Implement `.github/workflows/test.yml`**: Configure GitHub Actions to run pytest on push/PR
- **Implement `.github/workflows/lint.yml`**: Configure GitHub Actions to run Ruff, Black, mypy
- **Implement `.pre-commit-config.yaml`**: Add hooks for Ruff, Black, trailing whitespace, end-of-file
- **Install pre-commit hooks**: Run `pre-commit install` locally
- **Implement `Dockerfile`**: Create Docker image with Python base, dependencies, and uvicorn command
- **Deploy to Railway**: Connect GitHub repo to Railway, add environment variables, deploy
- **Configure production GitHub webhook**: Update webhook URL to Railway deployment URL
- **Test production deployment**: Create a PR and verify the agent reviews it successfully
- **Update `README.md`**: Add project overview, setup instructions, usage guide, architecture diagram
- **Add evaluation tests in `tests/evals/test_review_quality.py`**: Test agent identifies security issues, provides good feedback
- **Monitor and iterate**: Check Logfire dashboard (if configured), review agent performance, improve prompts

## Project Structure

```
AI-Code-Reviewer/
├── src/
│   ├── config/          # Settings and configuration
│   ├── models/          # Data models (dependencies, outputs, GitHub types)
│   ├── agents/          # AI agent definitions
│   ├── tools/           # GitHub interaction tools
│   ├── utils/           # Utilities (logging, filters)
│   ├── services/        # External service wrappers
│   ├── api/             # FastAPI endpoints
│   └── main.py          # Application entry point
├── tests/
│   ├── unit/            # Unit tests
│   ├── integration/     # Integration tests
│   └── evals/           # AI output quality evaluations
├── .github/workflows/   # CI/CD pipelines
└── pyproject.toml       # Dependencies and tool configuration
```

## Environment Variables

See `.env.example` for required configuration:
- `OPENAI_API_KEY` - OpenAI API key
- `GITHUB_TOKEN` - GitHub personal access token
- `GITHUB_WEBHOOK_SECRET` - Secret for webhook verification
- `LOGFIRE_TOKEN` - (Optional) Pydantic Logfire token for observability

## License

MIT
