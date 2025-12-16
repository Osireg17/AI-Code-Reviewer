# AI Code Review Agent

Automated GitHub PR code review using Pydantic AI and OpenAI.

## Features

- Automated code review on GitHub pull requests
- RAG-powered style guide recommendations using Pinecone
- Inline comments with severity levels (critical, warning, suggestion)
- Caching mechanism to reduce redundant API calls
- FastAPI webhook server for GitHub integration

## Development Setup

### Prerequisites

- Python 3.10+
- GitHub App credentials
- OpenAI API key
- Pinecone API key (optional, for RAG features)

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/AI-Code-Reviewer.git
cd AI-Code-Reviewer

# Install dependencies
pip install -e ".[dev]"
```

### Pre-commit Hooks

This project uses pre-commit hooks to ensure code quality before commits.

**Install and setup:**

```bash
# Install pre-commit
pip install pre-commit

# Install git hooks
pre-commit install

# Generate secrets baseline (first time only)
detect-secrets scan > .secrets.baseline

# Run hooks manually on all files
pre-commit run --all-files
```

**Configured hooks:**
- **ruff** - Fast Python linting and formatting
- **detect-secrets** - Secrets scanning
- **bandit** - Security vulnerability checking
- **pre-commit-hooks** - Trailing whitespace, EOF, large files, private keys

**Note:** Type checking with mypy runs separately (not in pre-commit) for speed. Run manually with `mypy src/`

**Skip hooks for quick commits:**
```bash
# Skip all hooks
git commit -m "message" --no-verify
```

### Running Tests

```bash
# Run all tests with coverage
pytest --cov=src --cov-report=term-missing --cov-report=html

# Run specific test file
pytest tests/unit/test_agents/test_code_reviewer.py -v

# Run tests in parallel
pytest -n auto
```

### Code Quality Checks

```bash
# Format code
black .

# Lint and auto-fix
ruff check --fix .

# Type check
mypy src/

# Security scan
bandit -r src/
```

## Configuration

Set environment variables in `.env.local` (see `.env.example`):

```bash
# Required
OPENAI_API_KEY=sk-...
GITHUB_TOKEN=ghp_...  # Or use GitHub App credentials
GITHUB_WEBHOOK_SECRET=your-secret

# Optional - GitHub App
GITHUB_APP_ID=123456
GITHUB_APP_INSTALLATION_ID=987654
GITHUB_APP_PRIVATE_KEY_PATH=/path/to/key.pem

# Optional - RAG features
PINECONE_API_KEY=pc-...
PINECONE_INDEX_NAME=code-style-guides
```

## Architecture

The system follows a layered architecture with clear separation of concerns:

```mermaid
flowchart TB
    subgraph SourceControl["GitHub"]
        PR_EVENT["PR Event"]
        COMMENT_API["Comments API"]
    end

    subgraph Railway["Railway Deployment"]
        WEBHOOK["FastAPI Webhook<br/>(Enqueuer)"]
        REDIS[("Redis Queue<br/>• Events persisted<br/>• Retry config")]
        WORKER["RQ Worker Process<br/>• Pull & process<br/>• Auto-retry failures"]
    end

    subgraph ProcessingLayer["Review Processing"]
        REVIEW_ENGINE["Review Engine"]
        AI_AGENT["AI Agent + Tools"]
    end

    subgraph External["External Services"]
        GITHUB_API["GitHub API"]
        OPENAI["OpenAI API"]
        PINECONE["Pinecone"]
    end

    PR_EVENT -->|"HTTP POST"| WEBHOOK
    WEBHOOK -->|"Enqueue job<br/>(instant response)"| REDIS
    REDIS -->|"Pull job"| WORKER
    WORKER -->|"Execute"| REVIEW_ENGINE
    REVIEW_ENGINE --> AI_AGENT
    AI_AGENT --> GITHUB_API
    AI_AGENT --> OPENAI
    AI_AGENT --> PINECONE
    REVIEW_ENGINE -->|"Post results"| COMMENT_API

    style REDIS fill:#ffcccc,stroke:#ff0000
    style WORKER fill:#ccffcc,stroke:#00ff00
```

- **Agent**: `src/agents/code_reviewer.py` - Pydantic AI agent with tool registration
- **Tools**: `src/tools/` - GitHub API and RAG search tools
- **Services**: `src/services/` - RAG, authentication, and business logic
- **API**: `src/api/webhooks.py` - FastAPI webhook handlers
- **Models**: `src/models/` - Pydantic models for data validation

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for deployment instructions.

## Contributing

1. Create a feature branch
2. Make your changes
3. Run tests and quality checks
4. Submit a pull request

Pre-commit hooks will run automatically on commit. All checks must pass before merging.

## License

MIT
