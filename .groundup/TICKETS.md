# Semantic Codebase Indexing — Implementation Tickets

Feature: Replace GitHub keyword search with AST-aware semantic search using tree-sitter + Pinecone.

**Flow agreed:**
```
webhook → handle_pull_request_event → enqueue_review → run_review_job
  → handle_pr_review
      → index_changed_files  [NEW — runs first, before agent]
      → _run_code_review_agent  [agent now has search_codebase tool with semantic/exact_call mode]
```

Work through the tickets **in order** — each one depends on the previous.

---

## TICKET 1 — Add tree-sitter dependencies to `pyproject.toml`

**Do this first** so imports resolve before you start implementing the service.

**What to add** under `[project] dependencies` (match the format of existing entries):

```toml
"tree-sitter>=0.23",
"tree-sitter-python>=0.23",
"tree-sitter-javascript>=0.23",
"tree-sitter-typescript>=0.23",
"tree-sitter-go>=0.23",
"tree-sitter-java>=0.23",
```

**After adding, run:**
```bash
pip install -e ".[dev]"
```

**Verify it works:**
```python
import tree_sitter_python as tspython
from tree_sitter import Language, Parser
lang = Language(tspython.language())
parser = Parser(lang)
tree = parser.parse(b"def foo(): pass")
print(tree.root_node.sexp())
```

---

## TICKET 2 — Implement `src/services/codebase_index_service.py`

**Status:** Pseudocode already written in the file. Implement each method.

**What to build:** A service that reads changed PR files, parses them with tree-sitter to extract function signatures and call sites, embeds the extracted text with OpenAI, and upserts the vectors to a separate Pinecone index (`codebase-index`).

**Key decisions already made:**
- Each Pinecone vector = one function (signature + list of functions it calls)
- Namespace per repo: `owner/repo` → `owner__repo` (replace `/` with `__`)
- Deterministic vector ID: `f"{namespace}:{file_path}:{function_name}"` → same function re-indexed = overwrite, not duplicate
- Upsert in batches of 100 (`_PINECONE_UPSERT_BATCH_SIZE`)
- Single file parse error → skip + record reason, continue to next file
- Service unavailable or GitHub fetch fails → raise (abort entire review)

**Reference files:**
- `src/services/rag_service.py` — mirror this exactly for `__init__`, `is_available()`, embeddings client setup
- `src/queue/config.py:59` — `_sanitize_repo` shows the `owner__repo` namespace pattern
- `src/tools/github_tools.py:183` — `pr.get_files()` usage
- `src/tools/github_tools.py:295-303` — `repo.get_contents(path, ref=sha)` + `.decoded_content.decode("utf-8")`

**tree-sitter usage pattern:**
```python
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

lang = Language(tspython.language())
parser = Parser(lang)
tree = parser.parse(bytes(content, "utf-8"))
```

For other languages: `import tree_sitter_javascript as tsjs`, `import tree_sitter_go as tsgo`, etc.

**Extracting function defs and calls from the AST:**
- Function definition nodes: `node.type == "function_definition"` (Python), `"function_declaration"` (Go/JS/TS), `"method_declaration"` (Java)
- Function name: `node.child_by_field_name("name").text.decode("utf-8")`
- Call sites inside a function body: walk child nodes, find `node.type == "call"`, extract the function field
- Walk the tree recursively — calls can be nested inside conditionals, loops, etc.

**Embed text format per chunk:**
```
"def process_payment(amount: float, user_id: str) -> Receipt calls: db.charge, notify_user, logger.info"
```

**Metadata per vector:**
```python
{
    "file_path": "src/services/payment.py",
    "function_name": "process_payment",
    "calls": ["db.charge", "notify_user", "logger.info"],
    "language": "python"
}
```

**Tests to write** (`tests/unit/test_services/test_codebase_index_service.py`):

| Test | Setup | Assert |
|------|-------|--------|
| `test_is_available_false_when_no_key` | No pinecone_api_key | `is_available()` returns False |
| `test_detect_language_python` | `_detect_language("src/foo.py")` | returns `"python"` |
| `test_detect_language_typescript` | `_detect_language("src/foo.tsx")` | returns `"typescript"` |
| `test_detect_language_unsupported` | `_detect_language("src/foo.rb")` | returns `None` |
| `test_parse_functions_extracts_name_and_calls` | Simple Python source with one function calling another | Returns `[{"name": ..., "signature": ..., "calls": [...]}]` |
| `test_parse_functions_empty_file` | Pass `""` | Returns `[]` |
| `test_index_changed_files_skips_unsupported_language` | Mock `pr.get_files()` returning a `.rb` file | `result.files_skipped` has one entry, `files_indexed == 0` |
| `test_index_changed_files_skips_on_parse_error` | Mock `_parse_functions` raising | File skipped, not raised, `files_indexed == 0` |
| `test_index_changed_files_raises_on_github_fetch_failure` | Mock `repo.get_contents()` raising | Exception propagated to caller |
| `test_embed_and_upsert_batches_correctly` | 250 chunks, mock embeddings + pinecone | Pinecone upsert called 3 times (100, 100, 50) |

---

## TICKET 3 — Create `src/tools/codebase_search_tools.py`

**Status:** New file. Does not exist yet.

**What to build:** An agent tool function that searches the Pinecone codebase index. Two modes:
- `"semantic"` — embed the query, run vector similarity search (fuzzy, natural language queries)
- `"exact_call"` — use Pinecone metadata filter to find all functions that call a specific function name

**Reference:** `src/tools/rag_tools.py` — mirror the structure (takes `RunContext`, calls the service, returns a dict)

**Function signature:**
```python
async def search_codebase(
    ctx: RunContext[ReviewDependencies],
    query: str,
    mode: str = "semantic",          # "semantic" | "exact_call"
    language: str | None = None,
    top_k: int = 5,
) -> dict:
```

**`"semantic"` mode:** embed `query`, run vector similarity search in Pinecone under the repo's namespace. Optionally filter by `language` metadata field if provided.

**`"exact_call"` mode:** do NOT embed. Use Pinecone metadata filter:
```python
# query = "process_payment" → find all functions that call process_payment
filter_dict = {"calls": {"$in": [query]}}
index.query(
    vector=[0.0] * 1536,   # dummy vector — Pinecone requires one even for metadata-only queries
    filter=filter_dict,
    top_k=top_k,
    namespace=namespace,
    include_metadata=True,
)
```

**Namespace:** Pull `repo_full_name` from `ctx.deps.repo_full_name`, replace `/` with `__`.

**Return shape (success):**
```python
{
    "success": True,
    "mode": "exact_call",
    "query": "process_payment",
    "results_count": 2,
    "results": [
        {
            "function_name": "checkout",
            "file_path": "src/handlers/checkout.py",
            "signature": "async def checkout(cart: Cart) -> Order",
            "calls": ["process_payment", "send_receipt"],
            "score": 0.95
        }
    ]
}
```

**Return shape (service unavailable):**
```python
{"success": False, "error": "Codebase index unavailable", "results": []}
```

**Return shape (invalid mode):**
```python
{"success": False, "error": "Invalid mode 'fuzzy'. Use 'semantic' or 'exact_call'.", "results": []}
```

**Tests to write** (`tests/unit/test_tools/test_codebase_search_tools.py`):

| Test | Assert |
|------|--------|
| `test_semantic_mode_calls_vector_search` | Embeddings called with query, Pinecone queried, results returned |
| `test_exact_call_mode_uses_metadata_filter` | Embeddings NOT called, Pinecone queried with `$in` filter |
| `test_language_filter_applied` | Pinecone query includes `language` metadata filter |
| `test_service_unavailable_returns_error_dict` | `is_available()` returns False → `{"success": False, ...}` |
| `test_invalid_mode_returns_error_dict` | `mode="fuzzy"` → `{"success": False, "error": ...}` |

---

## TICKET 4 — Modify `src/api/handlers/pr_review_handler.py`

**Status:** File exists. One small addition.

**Where to add:** After line 80 (`deps = ReviewDependencies(...)` is fully constructed), before line 81 (`await _post_progress_comment_if_needed(...)`).

**Add this block:**
```python
# Index changed files for semantic codebase search — runs before agent
from src.services.codebase_index_service import codebase_index_service
if codebase_index_service.is_available():
    try:
        indexing_result = await codebase_index_service.index_changed_files(repo, pr)
        logger.info(
            "Indexed %d files for PR #%d (%d skipped)",
            indexing_result.files_indexed,
            pr_number,
            len(indexing_result.files_skipped),
        )
        for skipped in indexing_result.files_skipped:
            logger.debug("Skipped indexing %s: %s", skipped["file"], skipped["reason"])
    except Exception as e:
        logger.warning(
            "Codebase indexing failed for PR #%d, proceeding without it: %s",
            pr_number,
            e,
        )
else:
    logger.debug("Codebase index unavailable — skipping pre-indexing")
```

**Why swallow the exception:** indexing failure must not block the review. Log it and continue.

**Tests to write** (add to existing handler test file):

| Test | Assert |
|------|--------|
| `test_indexing_called_before_agent` | Mock both; assert `index_changed_files` called before `agent.run` |
| `test_review_continues_when_indexing_fails` | `index_changed_files` raises; `agent.run` still called |
| `test_indexing_skipped_when_unavailable` | `is_available()` returns False; `index_changed_files` not called |

---

## TICKET 5 — Modify `src/agents/code_reviewer.py`

**Status:** File exists. Two changes.

**Change 1 — Add the new `search_codebase` tool.** Add after the `search_style_guides` tool (currently ends around line 181):

```python
@code_review_agent.tool
async def search_codebase(
    ctx: RunContext[ReviewDependencies],
    query: str,
    mode: str = "semantic",
    language: str | None = None,
    top_k: int = 5,
) -> dict:
    """Search the indexed codebase for functions and call relationships.

    Use this before reviewing to understand how changed functions are used across the repo.
    Two modes:
      - "semantic": vector similarity — use for "how is X implemented?", "show me error handling patterns"
      - "exact_call": metadata filter — use for "what calls process_payment?" (impact analysis)

    Args:
        query: Function name (exact_call mode) or natural language question (semantic mode)
        mode: "semantic" | "exact_call"
        language: Optional filter by language (e.g. "python")
        top_k: Number of results (default: 5)

    Returns:
        Dict with results list — each result has function_name, file_path, signature, calls, score
    """
    from src.tools.codebase_search_tools import search_codebase as _search
    return await _search(ctx, query, mode, language, top_k)
```

**Change 2 — Remove the old `search_codebase` tool.** Find and delete the existing tool that calls `github_search_tools.search_codebase` (currently around lines 184–207). It uses GitHub keyword search and is being replaced.

After deleting it, check whether `github_search_tools` is still imported anywhere in this file:
```bash
grep -n "github_search_tools" src/agents/code_reviewer.py
```
If it only appeared in the deleted tool, remove it from the import on line 14 too.

**No new tests needed for this file** — the tool delegates entirely to `codebase_search_tools.py` which has its own tests.

---

## TICKET 6 — Deprecate `src/services/github_search_service.py`

First check if anything else still imports it:
```bash
grep -r "github_search_service" src/ tests/ --include="*.py"
```

Add a module-level deprecation warning at the top (after the module docstring):
```python
import warnings
warnings.warn(
    "github_search_service is deprecated. Use codebase_index_service for semantic codebase search.",
    DeprecationWarning,
    stacklevel=2,
)
```

Do not delete the file yet. Delete in a follow-up PR once you've confirmed no remaining callers after Ticket 5.

---

## TICKET 7 — Deprecate `src/tools/github_search_tools.py`

Same approach as Ticket 6. Check callers first:
```bash
grep -r "github_search_tools" src/ tests/ --include="*.py"
```

After Ticket 5 removes it from `code_reviewer.py`, this should have zero callers. Add deprecation warning, delete in follow-up.

---

## Verification checklist before opening a PR

```
[ ] pip install -e ".[dev]" succeeds with tree-sitter packages
[ ] pytest passes with no failures
[ ] ruff check --fix src/ tests/ clean
[ ] black src/ tests/ clean
[ ] mypy src/ clean
[ ] All TICKET 2 tests exist and pass
[ ] All TICKET 3 tests exist and pass
[ ] TICKET 4 handler tests pass
[ ] codebase_index_service singleton initialises without error when Pinecone key absent (is_available returns False, no crash)
[ ] new search_codebase tool registered in code_reviewer.py, old GitHub keyword tool removed
```

---

## File order summary

| Order | File | Action |
|-------|------|--------|
| 1 | `pyproject.toml` | Add tree-sitter deps |
| 2 | `src/services/codebase_index_service.py` | Implement pseudocode already in file |
| 3 | `src/tools/codebase_search_tools.py` | Create new file |
| 4 | `src/api/handlers/pr_review_handler.py` | Add indexing call before agent |
| 5 | `src/agents/code_reviewer.py` | Register new tool, remove old one |
| 6 | `src/services/github_search_service.py` | Add deprecation warning |
| 7 | `src/tools/github_search_tools.py` | Add deprecation warning |
