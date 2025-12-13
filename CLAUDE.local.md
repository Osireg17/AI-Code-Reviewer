# AI Code Reviewer

**Automated GitHub PR review bot using AI + RAG-powered coding standards**

## What This Is

An AI agent that automatically reviews pull requests on GitHub:
- Posts inline code comments with authoritative citations (PEP 8, Airbnb JS, OWASP)
- Uses RAG (Retrieval Augmented Generation) to reference real style guides
- Runs as a GitHub App webhook on Railway
- No persistent database - stateless design

**Status:** Implementation phase (Weekend 1-5 timeline)
**Cost:** ~$2-4/month (LLM + Pinecone + Railway)

---

## Tech Stack

- **Framework:** FastAPI (Python 3.10+)
- **AI Agent:** Pydantic AI + OpenAI (GPT-4o/GPT-4o-mini)
- **Vector DB:** Pinecone (for RAG knowledge base)
- **GitHub:** PyGithub + GitHub App authentication (JWT)
- **Deploy:** Railway with Docker
- **Testing:** pytest (80%+ coverage target)

**Key Dependencies:**
```
pydantic-ai, fastapi, uvicorn, pygithub, httpx
langchain, langchain-pinecone, pinecone-client
pyjwt[crypto], python-dotenv, pydantic-settings
```

---

## Project Structure

```
src/
├── agents/code_reviewer.py    # Main AI agent (caching, tools, system prompt)
├── api/webhooks.py             # GitHub webhook handler
├── config/settings.py          # Pydantic Settings (env vars)
├── models/                     # Pydantic models (dependencies, outputs, GitHub types)
├── services/                   # github_auth.py, rag_service.py
├── tools/                      # github_tools.py, rag_tools.py
└── main.py                     # FastAPI app entry point

tests/                          # unit/, integration/, evals/
scripts/                        # setup_pinecone.py, index_documents.py, test_github_app_auth.py
docs/                           # GITHUB_APP_SETUP.md, DOCKER.md
```

**Key Files:**
- `src/agents/code_reviewer.py` - Agent with 6 GitHub tools + 1 RAG tool
- `src/api/webhooks.py` - Webhook signature verification, background processing
- `src/services/github_auth.py` - GitHub App JWT/token management
- `src/services/rag_service.py` - Pinecone vector search for style guides
- `pyproject.toml` - All dependencies and tool configurations

---

## How This Works

### Architecture Flow
```
GitHub PR → FastAPI Webhook → AI Agent → Tools → Post Review
                                   ├─ fetch_pr_context()
                                   ├─ list_changed_files()
                                   ├─ get_file_diff()
                                   ├─ get_full_file()
                                   ├─ post_review_comment()
                                   ├─ post_summary_comment()
                                   └─ search_style_guides() → Pinecone
```

### Review Workflow (Agent's Process)
1. **Initialize** - Get PR metadata and file list (cached)
2. **Per File** - Get diff → Search style guides → Analyze → Post comments
3. **Summarize** - Post overall review with recommendations

### Key Design Decisions

**Incremental Processing:** One file at a time for predictable token usage
**Caching:** PR context and file lists cached in agent dependencies
**RAG Integration:** Every review backed by authoritative sources (not LLM memory)
**Stateless:** No database - GitHub is source of truth

---

## Development Commands

### Setup
```bash
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env.local
```

### Run Locally
```bash
uvicorn src.main:app --reload --port 8000
# In another terminal: ngrok http 8000
```

### Testing
```bash
pytest                                    # All tests
pytest --cov=src --cov-report=html        # With coverage
pytest tests/unit/test_github_auth.py -v  # Specific file
```

### Code Quality
```bash
ruff check --fix src/ tests/    # Lint + auto-fix
black src/ tests/               # Format
mypy src/                       # Type check
```

### RAG Setup (One-time)
```bash
python scripts/setup_pinecone.py       # Create index
python scripts/index_documents.py      # Index style guides
python scripts/test_rag.py             # Verify search
```

### Verify GitHub App Auth
```bash
python scripts/test_github_app_auth.py
```

---

## Environment Variables

**Required (local):**
```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

GITHUB_APP_ID=123456
GITHUB_APP_INSTALLATION_ID=987654
GITHUB_APP_PRIVATE_KEY_PATH=./your-app.private-key.pem
GITHUB_WEBHOOK_SECRET=your-secret

PINECONE_API_KEY=your-key
PINECONE_INDEX_NAME=code-style-guides
RAG_ENABLED=True

DEBUG=True
LOG_LEVEL=DEBUG
ENVIRONMENT=development
```

**Production (Railway):**
- Use `GITHUB_APP_PRIVATE_KEY` (full PEM content) instead of `_PATH`
- Set `DEBUG=False`, `ENVIRONMENT=production`

---

## Common Tasks

### Adding a Style Guide
1. Add PDF/MD to `Coding Conventions/`
2. Update `Coding Conventions/documents.yaml`
3. Run `python scripts/index_documents.py`

### Modifying Agent Behavior
Edit `src/agents/code_reviewer.py`:
- `SYSTEM_PROMPT` - Agent instructions
- `@code_review_agent.tool` - Tool definitions
- `validate_review_result()` - Post-processing

### Debugging Webhooks
```bash
railway logs --follow                  # Check Railway logs
python scripts/test_github_app_auth.py # Test auth
curl -X POST http://localhost:8000/webhook/github ... # Test signature
```

---

## Testing Strategy

**Coverage Targets:**
- `src/agents/` - 70%+ (agent behavior harder to test)
- `src/models/` - 95%+ (data validation)
- `src/services/` - 85%+ (auth, RAG)
- `src/tools/` - 85%+ (GitHub API)

**Key Tests:**
- `test_github_auth.py` - JWT, token caching, key loading
- `test_github_tools.py` - Mocked GitHub API calls
- `test_rag_service.py` - Vector search formatting
- `test_webhooks.py` - Signature verification, event handling

---

## Important Constraints

### Token Limits
- **LLM:** ~25k tokens per PR (5 files avg) = ~$0.05
- **Embeddings:** ~6k tokens for RAG searches = ~$0.005
- **Optimization:** File filtering, caching, incremental processing

### File Filtering (Skip These)
```
*.lock, *.min.js, *.min.css
dist/, build/, node_modules/, __pycache__/
*.db, *.sqlite, *.pdf, *.zip
.git/, .vscode/, .idea/
```

### GitHub App Auth Flow
1. Load private key (file or env var)
2. Generate JWT (10-min validity)
3. Exchange for installation token
4. Cache token (refresh before 5-min expiry)

---

## Security Notes

✅ **Secrets in env vars** - Never commit `.env.local` or `.pem` files
✅ **Webhook signature verification** - HMAC-SHA256 with constant-time comparison
✅ **Scoped GitHub permissions** - Read repo, write PR comments only
⚠️ **Code sent to OpenAI** - Review their privacy policy
⚠️ **No code stored** - Stateless design, only metadata in logs

---

## Deployment (Railway)

1. Connect GitHub repo to Railway
2. Set environment variables in Railway dashboard
3. Enable "Wait for CI" (optional but recommended)
4. Push to `main` → auto-deploy

**See:** `DEPLOYMENT.md` for complete guide

---

## Why RAG?

**Problem:** LLMs have imperfect memory of coding standards
**Solution:** Vector DB with authoritative sources (PEP 8, Airbnb JS, OWASP)

**Benefits:**
- ✅ Authoritative citations in every comment
- ✅ Language-specific rules properly handled
- ✅ Educational - developers learn *why* not just *what*
- ✅ Consistency across all reviews
- ✅ Extensible - add company guides later

**Example:**
```
Before RAG: "Variable should use snake_case"
After RAG:  "Variable should use snake_case per PEP 8 (Naming Conventions):
             'Variable names follow the same convention as function names.'
             Suggested: user_data
             Reference: https://peps.python.org/pep-0008/#naming-conventions"
```

---

## Performance Tips

1. **Use file filtering** - Skip generated/lock files (see `src/utils/filters.py`)
2. **Rely on caching** - Don't re-fetch PR context or file lists
3. **One file at a time** - Predictable cost, focused analysis
4. **Batch RAG queries** - One search per file/topic, not per issue

---

## Key Documentation

- `docs/GITHUB_APP_SETUP.md` - Complete GitHub App setup guide
- `docs/DOCKER.md` - Docker/Railway deployment
- `DEPLOYMENT.md` - Railway deployment walkthrough
- `.github/SETUP.md` - CI/CD configuration

**External:**
- [Pydantic AI](https://ai.pydantic.dev/)
- [Pinecone Docs](https://docs.pinecone.io/)
- [Railway Docs](https://docs.railway.app/)
- [GitHub Apps](https://docs.github.com/en/apps)

---

## Troubleshooting

**Auth fails:** Run `python scripts/test_github_app_auth.py`, check PEM format
**Webhook signature mismatch:** Verify `GITHUB_WEBHOOK_SECRET` matches, no whitespace
**RAG unavailable:** Run `python scripts/test_rag.py`, verify Pinecone index exists
**Tests fail in CI:** Check Python version (3.11, 3.12), review GitHub Actions logs

---

## Project Philosophy

**Simplicity first** - Minimal architecture, add complexity only when needed
**Quality over quantity** - Better to review fewer files well than many poorly
**Authority matters** - Back reviews with real standards via RAG
**Cost conscious** - Track and optimize token usage
**Well-tested** - 80%+ coverage target, comprehensive mocking

---

## Current Status

✅ **Completed:** Structure, GitHub App auth, webhooks, RAG service, core tools, unit tests
🚧 **In Progress:** Integration tests, AI evals, RAG indexing pipeline
⏳ **TODO:** Pre-commit hooks, production deployment, monitoring

**Timeline:** 5 weekends (32-42 hours estimated)
**Monthly Cost:** $2-4 (LLM + Pinecone + Railway free tier)

---

*Last Updated: December 2024*
