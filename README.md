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
    subgraph SourceControl["Source Control (GitHub)"]
        direction LR
        PR_EVENT["Pull Request<br/>Webhook Event"]
        COMMENT_API["Comment Interface"]
    end
    
    subgraph API_Layer["API Service Layer (Railway/FastAPI)"]
        WEBHOOK_DISPATCHER["Webhook Dispatcher"]
        TASK_QUEUE["Background Task Queue"]
        PR_REVIEW_ENGINE["PR Review Engine"]
    end
    
    subgraph AgentLayer["AI Agent Layer (code_reviewer.py)"]
        CODE_REVIEW_AGENT["Code Review Agent"]
        DEPENDENCY_CACHE[(Dependency Cache<br/>ReviewDependencies._cache)]
    end
    
    subgraph ToolingLayer["Tool Integration Layer"]
        GITHUB_INT["GitHub Integration Service<br/>• fetch_pr_context (cached)<br/>• list_changed_files (cached)<br/>• get_file_diff (cached)<br/>• get_full_file<br/>• post_review_comment (stateful)<br/>• post_summary_comment (stateful)"]
        STYLE_GUIDE_SERVICE["Style Guide Service<br/>• search_style_guides"]
    end
    
    subgraph ExternalServices["External Service Dependencies"]
        LLM_SERVICE["OpenAI GPT-4o"]
        VECTOR_DB["Pinecone Vector Database"]
        GITHUB_CLOUD_API["GitHub Cloud API"]
    end

    %% Primary Event Flow
    PR_EVENT -->|HTTP POST| WEBHOOK_DISPATCHER
    WEBHOOK_DISPATCHER -->|Enqueue Task| TASK_QUEUE
    TASK_QUEUE -->|Execute| PR_REVIEW_ENGINE
    PR_REVIEW_ENGINE -->|Instantiate| CODE_REVIEW_AGENT
    
    %% GitHub Data Retrieval Flow
    CODE_REVIEW_AGENT -->|Invoke| GITHUB_INT
    GITHUB_INT -->|Cache Check| DEPENDENCY_CACHE
    DEPENDENCY_CACHE -.->|Cache Hit<br/>Return Data| GITHUB_INT
    GITHUB_INT -->|Cache Miss| GITHUB_CLOUD_API
    GITHUB_CLOUD_API -->|API Response| GITHUB_INT
    GITHUB_INT -->|Cache Result| DEPENDENCY_CACHE
    
    %% State Management Flow
    GITHUB_INT -->|Set State Flags| DEPENDENCY_CACHE
    PR_REVIEW_ENGINE -->|Monitor State| DEPENDENCY_CACHE
    
    %% AI & Knowledge Flow
    CODE_REVIEW_AGENT -->|Query| STYLE_GUIDE_SERVICE
    STYLE_GUIDE_SERVICE <-->|Vector Search| VECTOR_DB
    CODE_REVIEW_AGENT <-->|LLM Generation| LLM_SERVICE
    
    %% Output Flow
    PR_REVIEW_ENGINE -->|State Evaluation| DEPENDENCY_CACHE
    PR_REVIEW_ENGINE -->|Conditional Post| COMMENT_API

    %% Styling
    style DEPENDENCY_CACHE fill:#fff9c4,stroke:#f57c00
    style GITHUB_INT fill:#e1f5ff,stroke:#0288d1
    style CODE_REVIEW_AGENT fill:#fff4e1,stroke:#ff9800
    
    %% Legend
    LEGEND["Symbol Legend:<br/>• (cached) = Tool with cache support<br/>• (stateful) = Tool that sets system state"]
    GITHUB_INT -.-> LEGEND
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
