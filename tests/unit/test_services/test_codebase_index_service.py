"""Unit tests for the CodebaseIndexService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.codebase_index_service import (
    CodebaseIndexService,
)

# ==========================================
# 1. INITIALIZATION & AVAILABILITY TESTS
# ==========================================


@patch("src.services.codebase_index_service.settings")
def test_init_no_pinecone_api_key(mock_settings):
    """Test service initialization when Pinecone API key is missing."""
    mock_settings.pinecone_api_key = None
    service = CodebaseIndexService()
    assert not service.is_available()
    assert service.pc is None
    assert service.index is None
    assert service.embeddings is None


@patch("src.services.codebase_index_service.settings")
@patch("src.services.codebase_index_service.Pinecone")
def test_init_index_not_exists(mock_pinecone, mock_settings):
    """Test service initialization when the specified index does not exist in Pinecone."""
    mock_settings.pinecone_api_key = "test-api-key"  # pragma: allowlist secret
    mock_settings.pinecone_index_name = "target-index"

    mock_pc = MagicMock()
    mock_pinecone.return_value = mock_pc

    # Mock Pinecone list_indexes returning other index names
    mock_index_info = MagicMock()
    mock_index_info.name = "other-index"
    mock_pc.list_indexes.return_value.indexes = [mock_index_info]

    service = CodebaseIndexService()
    assert not service.is_available()
    assert service.pc is None
    assert service.index is None
    assert service.embeddings is None


@patch("src.services.codebase_index_service.settings")
@patch("src.services.codebase_index_service.Pinecone")
def test_init_exception_raised(mock_pinecone, mock_settings):
    """Test initialization when an exception is raised by the Pinecone client."""
    mock_settings.pinecone_api_key = "test-api-key"  # pragma: allowlist secret
    mock_pinecone.side_effect = Exception("Connection error")

    service = CodebaseIndexService()
    assert not service.is_available()
    assert service.pc is None
    assert service.index is None
    assert service.embeddings is None


def test_is_available():
    """Test is_available returns True only when all components are initialized."""
    service = CodebaseIndexService()

    # Force unavailable state
    service.pc = None
    assert not service.is_available()

    service.pc = MagicMock()
    service.index = MagicMock()
    service.embeddings = MagicMock()
    assert service.is_available()


# ==========================================
# 2. LANGUAGE DETECTION TESTS
# ==========================================


@pytest.mark.parametrize(
    "file_path,expected_language",
    [
        ("test.py", "python"),
        ("path/to/script.js", "javascript"),
        ("component.jsx", "javascript"),
        ("src/types.ts", "typescript"),
        ("app.tsx", "typescript"),
        ("main.go", "go"),
        ("Service.java", "java"),
        ("styles.css", None),
        ("README.md", None),
        ("config.json", None),
    ],
)
def test_detect_language(file_path, expected_language):
    """Test language detection based on file extensions."""
    service = CodebaseIndexService()
    assert service._detect_language(file_path) == expected_language


# ==========================================
# 3. AST PARSING TESTS
# ==========================================


def test_parse_functions_python():
    """Test parsing of python function definitions using tree-sitter."""
    service = CodebaseIndexService()
    code = """
def hello_world(name: str) -> None:
    print(f"Hello, {name}!")
    another_call()

class Helper:
    def helper_method(self):
        self.do_something()
"""
    results = service._parse_functions(code, "python")
    assert len(results) == 2

    # 1. Test hello_world
    assert results[0]["name"] == "hello_world"
    assert results[0]["signature"] == "hello_world(name: str) -> None"
    assert "print" in results[0]["calls"]
    assert "another_call" in results[0]["calls"]

    # 2. Test helper_method
    assert results[1]["name"] == "helper_method"
    assert results[1]["signature"] == "helper_method(self)"
    assert "do_something" in results[1]["calls"]


def test_parse_functions_unsupported_language_raises_error():
    """Test that parsing functions in an unsupported language raises a ValueError."""
    service = CodebaseIndexService()
    with pytest.raises(ValueError, match="Unrecognized language: unsupported"):
        service._parse_functions("def test(): pass", "unsupported")


@patch("src.services.codebase_index_service.get_language")
def test_parse_functions_load_language_error(mock_get_language):
    """Test that _parse_functions raises ValueError when tree-sitter language load fails."""
    mock_get_language.side_effect = Exception("Load failure")
    service = CodebaseIndexService()
    with pytest.raises(
        ValueError, match="Failed to load language python: Load failure"
    ):
        service._parse_functions("def test(): pass", "python")


# ==========================================
# 4. EMBEDDING & UPSERT TESTS
# ==========================================


@pytest.mark.asyncio
async def test_embed_and_upsert_service_unavailable():
    """Test embed_and_upsert raises RuntimeError if codebase service is unavailable."""
    service = CodebaseIndexService()
    with (
        patch.object(service, "is_available", return_value=False),
        pytest.raises(RuntimeError, match="Codebase index service is not available"),
    ):
        await service._embed_and_upsert([{"name": "test"}], "namespace", "file.py")


@pytest.mark.asyncio
async def test_embed_and_upsert_empty_chunks():
    """Test that embed_and_upsert does nothing and returns if chunks list is empty."""
    service = CodebaseIndexService()
    service.pc = MagicMock()
    service.index = MagicMock()
    service.embeddings = MagicMock()

    await service._embed_and_upsert([], "namespace", "file.py")
    service.index.upsert.assert_not_called()


@pytest.mark.asyncio
@patch("src.services.codebase_index_service._PINECONE_UPSERT_BATCH_SIZE", 2)
async def test_embed_and_upsert_success_with_batching():
    """Test successful embedding and upserting with batching logic."""
    service = CodebaseIndexService()
    service.pc = MagicMock()
    service.index = MagicMock()
    service.embeddings = MagicMock()

    # Mock asynchronous embeddings generator
    service.embeddings.aembed_documents = AsyncMock(
        return_value=[[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
    )

    chunks = [
        {"name": "func_one", "signature": "def func_one()", "calls": ["call_a"]},
        {"name": "func_two", "signature": "def func_two()", "calls": ["call_b"]},
        {"name": "func_three", "signature": "def func_three()", "calls": []},
    ]

    await service._embed_and_upsert(chunks, "test_owner__test_repo", "src/main.py")

    # Verify embeddings were requested for all texts
    expected_texts = [
        "def func_one()\ncalls: call_a",
        "def func_two()\ncalls: call_b",
        "def func_three()\ncalls: ",
    ]
    service.embeddings.aembed_documents.assert_called_once_with(expected_texts)

    # Since batch size is patched to 2, upsert should be called twice:
    # Batch 1 (size 2), Batch 2 (size 1)
    assert service.index.upsert.call_count == 2

    # Verify first batch parameters
    call_args_1 = service.index.upsert.call_args_list[0]
    kwargs_1 = call_args_1.kwargs
    assert kwargs_1["namespace"] == "test_owner__test_repo"
    assert len(kwargs_1["vectors"]) == 2
    assert kwargs_1["vectors"][0] == (
        "test_owner__test_repo:src/main.py:func_one",
        [0.1, 0.2],
        {
            "file_path": "src/main.py",
            "function_name": "func_one",
            "calls": ["call_a"],
            "language": "python",
            "text": "def func_one()\ncalls: call_a",
        },
    )

    # Verify second batch parameters
    call_args_2 = service.index.upsert.call_args_list[1]
    kwargs_2 = call_args_2.kwargs
    assert kwargs_2["namespace"] == "test_owner__test_repo"
    assert len(kwargs_2["vectors"]) == 1
    assert kwargs_2["vectors"][0] == (
        "test_owner__test_repo:src/main.py:func_three",
        [0.5, 0.6],
        {
            "file_path": "src/main.py",
            "function_name": "func_three",
            "calls": [],
            "language": "python",
            "text": "def func_three()\ncalls: ",
        },
    )


# ==========================================
# 5. INDEX CHANGED FILES TESTS
# ==========================================


@pytest.mark.asyncio
async def test_index_changed_files_service_unavailable():
    """Test index_changed_files raises RuntimeError if service is not available."""
    service = CodebaseIndexService()
    repo = MagicMock()
    pr = MagicMock()
    with (
        patch.object(service, "is_available", return_value=False),
        pytest.raises(RuntimeError, match="Codebase index service is not available"),
    ):
        await service.index_changed_files(repo, pr)


@pytest.mark.asyncio
async def test_index_changed_files_pr_error():
    """Test that index_changed_files raises RuntimeError if get_files fails."""
    service = CodebaseIndexService()
    service.pc = MagicMock()
    service.index = MagicMock()
    service.embeddings = MagicMock()

    pr = MagicMock()
    pr.get_files.side_effect = Exception("GitHub API rate limit")

    # Setup owner and repo information
    pr.base.repo.owner.login = "owner"
    pr.base.repo.name = "repo"

    repo = MagicMock()

    with pytest.raises(RuntimeError, match="Failed to get changed files from PR"):
        await service.index_changed_files(repo, pr)


@pytest.mark.asyncio
async def test_index_changed_files_success_flow():
    """Test the complete successful flow of index_changed_files including skipping."""
    service = CodebaseIndexService()
    service.pc = MagicMock()
    service.index = MagicMock()
    service.embeddings = MagicMock()

    # Mock PR file list:
    # 1. Removed file (should be skipped)
    # 2. Unsupported file (should be skipped)
    # 3. Supported python file with functions (should be indexed)
    # 4. Supported python file with no functions (should be skipped)
    # 5. Supported file that fails content fetching (should fail whole execution)

    file_removed = MagicMock()
    file_removed.filename = "old.py"
    file_removed.status = "removed"

    file_unsupported = MagicMock()
    file_unsupported.filename = "doc.md"
    file_unsupported.status = "modified"

    file_valid = MagicMock()
    file_valid.filename = "main.py"
    file_valid.status = "modified"

    file_empty = MagicMock()
    file_empty.filename = "empty.py"
    file_empty.status = "added"

    pr = MagicMock()
    pr.get_files.return_value = [file_removed, file_unsupported, file_valid, file_empty]
    pr.base.repo.owner.login = "Owner"
    pr.base.repo.name = "Repo"
    pr.head.sha = "commitsha123"

    # Mock repo.get_contents
    repo = MagicMock()
    github_file_valid = MagicMock()
    github_file_valid.decoded_content = b"def run():\n    pass"

    github_file_empty = MagicMock()
    github_file_empty.decoded_content = b"# Just comments"

    def get_contents_side_effect(filename, ref):
        if filename == "main.py":
            return github_file_valid
        if filename == "empty.py":
            return github_file_empty
        return None

    repo.get_contents.side_effect = get_contents_side_effect

    # Mock AST parser and embed/upsert
    with (
        patch.object(service, "_parse_functions") as mock_parse,
        patch.object(
            service, "_embed_and_upsert", new_callable=AsyncMock
        ) as mock_embed,
    ):
        mock_parse.side_effect = lambda content, lang: (
            [{"name": "run", "signature": "def run()", "calls": []}]
            if content == "def run():\n    pass"
            else []
        )

        result = await service.index_changed_files(repo, pr)

        # Assertions on indexing results
        assert result.files_indexed == 1
        assert len(result.files_skipped) == 3

        # Verify skipped reasons
        assert result.files_skipped[0] == {"file": "old.py", "reason": "file removed"}
        assert result.files_skipped[1] == {
            "file": "doc.md",
            "reason": "unsupported language",
        }
        assert result.files_skipped[2] == {
            "file": "empty.py",
            "reason": "no functions found",
        }

        # Verify embedding call
        mock_embed.assert_called_once_with(
            [{"name": "run", "signature": "def run()", "calls": []}],
            "owner__repo",
            "main.py",
        )


@pytest.mark.asyncio
async def test_index_changed_files_fetch_failure_raises():
    """Test that failure to fetch file content raises RuntimeError and stops indexing."""
    service = CodebaseIndexService()
    service.pc = MagicMock()
    service.index = MagicMock()
    service.embeddings = MagicMock()

    file_valid = MagicMock()
    file_valid.filename = "main.py"
    file_valid.status = "modified"

    pr = MagicMock()
    pr.get_files.return_value = [file_valid]
    pr.base.repo.owner.login = "owner"
    pr.base.repo.name = "repo"
    pr.head.sha = "sha"

    repo = MagicMock()
    repo.get_contents.side_effect = Exception("GitHub API error")

    with pytest.raises(RuntimeError, match="Failed to fetch content for file main.py"):
        await service.index_changed_files(repo, pr)


@pytest.mark.asyncio
async def test_index_changed_files_parse_error_skips():
    """Test that a parser error in one file skips it but doesn't crash the service."""
    service = CodebaseIndexService()
    service.pc = MagicMock()
    service.index = MagicMock()
    service.embeddings = MagicMock()

    file_fail = MagicMock()
    file_fail.filename = "bad.py"
    file_fail.status = "modified"

    file_ok = MagicMock()
    file_ok.filename = "good.py"
    file_ok.status = "modified"

    pr = MagicMock()
    pr.get_files.return_value = [file_fail, file_ok]
    pr.base.repo.owner.login = "owner"
    pr.base.repo.name = "repo"
    pr.head.sha = "sha"

    repo = MagicMock()
    github_file = MagicMock()
    github_file.decoded_content = b"content"
    repo.get_contents.return_value = github_file

    with (
        patch.object(service, "_parse_functions") as mock_parse,
        patch.object(
            service, "_embed_and_upsert", new_callable=AsyncMock
        ) as mock_embed,
    ):
        # First file raises error, second file returns function
        mock_parse.side_effect = [
            Exception("Syntax error"),
            [{"name": "foo", "signature": "def foo()", "calls": []}],
        ]

        result = await service.index_changed_files(repo, pr)

        assert result.files_indexed == 1
        assert len(result.files_skipped) == 1
        assert result.files_skipped[0] == {
            "file": "bad.py",
            "reason": "parse error: Syntax error",
        }

        # Verify only the second file was embedded
        mock_embed.assert_called_once_with(
            [{"name": "foo", "signature": "def foo()", "calls": []}],
            "owner__repo",
            "good.py",
        )


@pytest.mark.asyncio
async def test_index_changed_files_embed_failure_raises():
    """Test that embedding/upsert error raises RuntimeError and stops indexing."""
    service = CodebaseIndexService()
    service.pc = MagicMock()
    service.index = MagicMock()
    service.embeddings = MagicMock()

    file_valid = MagicMock()
    file_valid.filename = "main.py"
    file_valid.status = "modified"

    pr = MagicMock()
    pr.get_files.return_value = [file_valid]
    pr.base.repo.owner.login = "owner"
    pr.base.repo.name = "repo"
    pr.head.sha = "sha"

    repo = MagicMock()
    github_file = MagicMock()
    github_file.decoded_content = b"def run():\n    pass"
    repo.get_contents.return_value = github_file

    with (
        patch.object(service, "_parse_functions") as mock_parse,
        patch.object(
            service, "_embed_and_upsert", new_callable=AsyncMock
        ) as mock_embed,
    ):
        mock_parse.return_value = [
            {"name": "run", "signature": "def run()", "calls": []}
        ]
        mock_embed.side_effect = Exception("Pinecone write timeout")

        with pytest.raises(
            RuntimeError,
            match="Failed to embed and upsert file main.py to codebase index",
        ):
            await service.index_changed_files(repo, pr)
