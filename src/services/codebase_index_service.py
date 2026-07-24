"""Codebase semantic indexing service using tree-sitter AST parsing and Pinecone."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from github.PullRequest import PullRequest
from github.Repository import Repository
from langchain_openai import OpenAIEmbeddings
from pinecone import Pinecone
from tree_sitter import Parser
from tree_sitter_languages import get_language  # type: ignore[import-untyped]

from src.config.settings import settings

logger = logging.getLogger(__name__)

_PINECONE_UPSERT_BATCH_SIZE = 100
# Dimension of text-embedding-3-small. Used for the dummy vector in exact_call metadata queries.
# If the embedding model changes, update this constant to match the new model's output dimension.
_EMBEDDING_DIMENSION = 1536


@dataclass
class IndexingResult:
    files_indexed: int = 0
    files_skipped: list[dict] = field(
        default_factory=list
    )  # [{"file": str, "reason": str}]


class CodebaseIndexService:
    def __init__(self) -> None:
        self.pc = None
        self.index = None
        self.embeddings = None
        if not settings.pinecone_api_key:
            logger.warning(
                "Pinecone API key not found - RAG service will be unavailable"
            )
            self.pc = None
            self.index = None
            self.embeddings = None
            return
        try:
            self.pc = Pinecone(api_key=settings.pinecone_api_key)
            existing_indexes = [idx.name for idx in self.pc.list_indexes().indexes]
            if settings.pinecone_codebase_index_name not in existing_indexes:
                logger.error(
                    f"Pinecone index '{settings.pinecone_codebase_index_name}' does not exist. "
                    f"Available indexes: {existing_indexes}. "
                    f"Run 'python scripts/setup_pinecone.py' to create it."
                )
                self.pc = None
                self.index = None
                self.embeddings = None
                return
            self.index = self.pc.Index(settings.pinecone_codebase_index_name)
            api_key_callable: Callable[[], str] | None = None
            if settings.openai_api_key:

                def api_key_callable() -> str:
                    assert settings.openai_api_key is not None
                    return settings.openai_api_key

            self.embeddings = OpenAIEmbeddings(
                model=settings.embedding_model,
                api_key=api_key_callable,
            )
            logger.info(
                f"Codebase index service initialized with index: {settings.pinecone_codebase_index_name}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize codebase index service: {e}")
            self.pc = None
            self.index = None
            self.embeddings = None

    def is_available(self) -> bool:
        return (
            self.pc is not None
            and self.index is not None
            and self.embeddings is not None
        )

    async def index_changed_files(
        self,
        repo: Repository,
        pr: PullRequest,
    ) -> IndexingResult:
        if not self.is_available():
            raise RuntimeError("Codebase index service is not available")

        # 2. COMPUTE the namespace for this repo (sanitise owner/repo → owner__repo)
        owner = pr.base.repo.owner.login.lower()
        repo_name = pr.base.repo.name.lower()
        namespace = f"{owner}__{repo_name}"

        # 3. GET the list of changed files from the pull request
        try:
            files = pr.get_files()
        except Exception as e:
            raise RuntimeError(f"Failed to get changed files from PR: {e}") from e

        files_indexed = 0
        skipped_files = []

        # 4. FOR EACH changed file:
        for file in files:
            # Skip removed files safely and delete their vectors
            if getattr(file, "status", None) == "removed":
                try:
                    if self.index:
                        self.index.delete(
                            filter={"file_path": file.filename}, namespace=namespace
                        )
                        logger.info(
                            f"Deleted vectors for removed file {file.filename} in namespace {namespace}"
                        )
                        reason = "file removed — vectors deleted"
                    else:
                        reason = "file removed — codebase index unavailable"
                except Exception as e:
                    logger.warning(f"Failed to delete vectors for {file.filename}: {e}")
                    reason = f"file removed — failed to delete vectors: {e}"
                skipped_files.append({"file": file.filename, "reason": reason})
                continue

            # a. DETERMINE whether the file's language is supported (CALL _detect_language)
            #    IF unsupported, record skip reason "unsupported language", continue to next file
            lang = self._detect_language(file.filename)
            if not lang:
                skipped_files.append(
                    {"file": file.filename, "reason": "unsupported language"}
                )
                continue

            # b. GET the full file content at the PR head commit SHA
            #    IF fetch fails, signal that indexing cannot proceed (whole-service failure)
            try:
                github_file = repo.get_contents(file.filename, ref=pr.head.sha)
                if not github_file:
                    raise ValueError("Empty response from GitHub get_contents")
                if isinstance(github_file, list):
                    raise ValueError("Expected a file but received a directory listing")

                content_bytes = github_file.decoded_content
                content = content_bytes.decode("utf-8")
            except Exception as e:
                # GitHub file fetch fails → signal that indexing cannot proceed
                raise RuntimeError(
                    f"Failed to fetch content for file {file.filename} at ref {pr.head.sha}: {e}"
                ) from e

            # c. CALL _parse_functions with the file content and detected language
            #    IF parsing fails, record skip reason "parse error: <detail>", continue to next file
            try:
                chunks = self._parse_functions(content, lang)
            except Exception as e:
                skipped_files.append(
                    {"file": file.filename, "reason": f"parse error: {e}"}
                )
                continue

            # d. IF no functions were extracted, record skip reason "no functions found", continue
            if not chunks:
                skipped_files.append(
                    {"file": file.filename, "reason": "no functions found"}
                )
                continue

            # e. CALL _embed_and_upsert with the extracted function chunks and namespace
            #    IF embed/upsert fails, signal that indexing cannot proceed
            try:
                await self._embed_and_upsert(chunks, namespace, file.filename)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to embed and upsert file {file.filename} to codebase index: {e}"
                ) from e

            # f. INCREMENT files_indexed count
            files_indexed += 1

        # 5. RETURN IndexingResult with final counts and skipped file list
        return IndexingResult(files_indexed=files_indexed, files_skipped=skipped_files)

    def _detect_language(self, file_path: str) -> str | None:
        file_extension = Path(file_path).suffix.lower().lstrip(".")
        if file_extension == "py":
            return "python"
        elif file_extension in ["js", "jsx"]:
            return "javascript"
        elif file_extension in ["ts", "tsx"]:
            return "typescript"
        elif file_extension == "go":
            return "go"
        elif file_extension == "java":
            return "java"
        else:
            return None

    def _parse_functions(
        self,
        content: str,
        language: str,
    ) -> list[dict]:
        language_map = {
            "python": "python",
            "javascript": "javascript",
            "typescript": "typescript",
            "go": "go",
            "java": "java",
        }

        normalized_lang = language_map.get(language.lower())
        if not normalized_lang:
            raise ValueError(f"Unrecognized language: {language}")

        try:
            lang = get_language(normalized_lang)
        except Exception as e:
            raise ValueError(f"Failed to load language {language}: {e}")  # noqa: B904

        parser = Parser()
        parser.set_language(lang)

        content_bytes = bytes(content, "utf-8")
        tree = parser.parse(content_bytes)
        root = tree.root_node

        func_query_patterns = {
            "python": "(function_definition) @function",
            "javascript": """
                (function_declaration) @function
                (function) @function
                (arrow_function) @function
                (generator_function_declaration) @function
                (method_definition) @function
            """,
            "typescript": """
                (function_declaration) @function
                (function) @function
                (arrow_function) @function
                (generator_function_declaration) @function
                (method_definition) @function
            """,
            "go": """
                (function_declaration) @function
                (method_declaration) @function
            """,
            "java": """
                (method_declaration) @function
                (constructor_declaration) @function
            """,
        }

        query_string = func_query_patterns.get(normalized_lang, "")
        if not query_string:
            return []

        try:
            query = lang.query(query_string)
            captures = query.captures(root)
        except Exception as e:
            logger.error(
                f"Error querying AST for functions in language {language}: {e}"
            )
            return []

        call_query_patterns = {
            "python": """
                (call function: (identifier) @call_name)
                (call function: (attribute attribute: (identifier) @call_name))
            """,
            "javascript": """
                (call_expression function: (identifier) @call_name)
                (call_expression function: (member_expression property: (property_identifier) @call_name))
            """,
            "typescript": """
                (call_expression function: (identifier) @call_name)
                (call_expression function: (member_expression property: (property_identifier) @call_name))
            """,
            "go": """
                (call_expression function: (identifier) @call_name)
                (call_expression function: (selector_expression field: (field_identifier) @call_name))
            """,
            "java": """
                (method_invocation name: (identifier) @call_name)
            """,
        }

        call_pattern = call_query_patterns.get(normalized_lang, "")
        call_query = lang.query(call_pattern) if call_pattern else None

        results: list[dict[str, str | list[str]]] = []
        for func_node, _ in captures:
            func_info = self._extract_function_info(
                func_node=func_node,
                call_query=call_query,
                content_bytes=content_bytes,
            )
            if func_info:
                results.append(func_info)

        return results

    def _extract_function_info(
        self,
        func_node: Any,
        call_query: Any,
        content_bytes: bytes,
    ) -> dict[str, str | list[str]] | None:
        name_node = func_node.child_by_field_name("name")
        if not name_node:
            return None

        function_name = content_bytes[name_node.start_byte : name_node.end_byte].decode(
            "utf-8"
        )

        body_node = func_node.child_by_field_name("body")
        if body_node:
            signature_bytes = content_bytes[name_node.start_byte : body_node.start_byte]
        else:
            signature_bytes = content_bytes[name_node.start_byte : func_node.end_byte]

        signature_text = signature_bytes.decode("utf-8")
        signature = signature_text.strip()
        while signature and (
            signature[-1] in ("{", ":", ";", " ") or signature.endswith("\n")
        ):
            signature = signature[:-1].strip()

        calls: list[str] = []
        if body_node and call_query:
            try:
                call_captures = call_query.captures(body_node)
                for call_node, _ in call_captures:
                    call_name = content_bytes[
                        call_node.start_byte : call_node.end_byte
                    ].decode("utf-8")
                    if call_name not in calls:
                        calls.append(call_name)
            except Exception as e:
                logger.warning(
                    f"Error querying call expressions inside function {function_name}: {e}"
                )

        return {"name": function_name, "signature": signature, "calls": calls}

    async def _embed_and_upsert(
        self,
        chunks: list[dict],
        namespace: str,
        file_path: str,
    ) -> None:
        embeddings_service = self.embeddings
        index = self.index
        if embeddings_service is None or index is None:
            raise RuntimeError("Codebase index service components are not initialized")

        if not chunks:
            return

        texts_to_embed = []
        metadata_list = []
        vector_ids = []

        language = self._detect_language(file_path) or "unknown"

        # 1. FOR EACH chunk, BUILD the text to embed:
        #    COMBINE signature text + "calls: " + comma-separated call names
        #
        # 2. BUILD the metadata dict for each chunk:
        #    {file_path, function_name, calls (list), language}
        #
        # 3. COMPUTE a deterministic vector ID per function:
        #    COMBINE namespace + file_path + function name
        for chunk in chunks:
            function_name = chunk.get("name", "")
            signature = chunk.get("signature", "")
            calls = chunk.get("calls", [])

            calls_str = ", ".join(calls)
            text = f"{signature}\ncalls: {calls_str}"
            texts_to_embed.append(text)

            metadata = {
                "file_path": file_path,
                "function_name": function_name,
                "calls": calls,
                "language": language,
                "text": text,
            }
            metadata_list.append(metadata)

            vector_id = f"{namespace}:{file_path}:{function_name}"
            vector_ids.append(vector_id)

        # 4. COLLECT all (id, embedding, metadata) tuples into a list
        #    CALL the embeddings model with all texts in one request (batch embed)
        embeddings = await embeddings_service.aembed_documents(texts_to_embed)

        vectors = [
            (vector_ids[i], embeddings[i], metadata_list[i]) for i in range(len(chunks))
        ]

        # 5. FOR EACH batch of _PINECONE_UPSERT_BATCH_SIZE vectors:
        #    UPSERT the batch to Pinecone under the given namespace
        for i in range(0, len(vectors), _PINECONE_UPSERT_BATCH_SIZE):
            batch = vectors[i : i + _PINECONE_UPSERT_BATCH_SIZE]
            index.upsert(vectors=batch, namespace=namespace)

    async def search_codebase(
        self,
        query: str,
        namespace: str,
        mode: str = "semantic",
        language: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search the codebase semantic index for matching code patterns.

        Args:
            query: Search query string or function name
            namespace: Repo namespace (e.g. "owner__repo")
            mode: Search mode ("semantic" or "exact_call")
            language: Optional language filter
            top_k: Number of results to return

        Returns:
            List of matching functions with metadata and scores
        """
        if not self.is_available():
            logger.warning("Codebase index service is not available")
            return []

        index = self.index
        if index is None:
            raise RuntimeError("Pinecone index is not initialized")

        filter_dict: dict[str, Any] = {}
        if language:
            filter_dict["language"] = language.lower()

        if mode == "semantic":
            embeddings_service = self.embeddings
            if embeddings_service is None:
                raise RuntimeError("Embeddings service is not initialized")
            # Embed the query string
            query_vector = await embeddings_service.aembed_query(query)

            response = index.query(
                vector=query_vector,
                filter=filter_dict or None,
                top_k=top_k,
                namespace=namespace,
                include_metadata=True,
            )
        elif mode == "exact_call":
            filter_dict["calls"] = {"$in": [query]}

            response = index.query(
                vector=[0.0] * _EMBEDDING_DIMENSION,
                filter=filter_dict,
                top_k=top_k,
                namespace=namespace,
                include_metadata=True,
            )
        else:
            raise ValueError(f"Invalid mode '{mode}'")

        results_list = []
        for match in response.matches:
            metadata = match.metadata or {}
            text = metadata.get("text", "")
            signature = text.split("\ncalls:")[0] if "\ncalls:" in text else text

            results_list.append(
                {
                    "function_name": metadata.get("function_name", "Unknown"),
                    "file_path": metadata.get("file_path", "Unknown"),
                    "signature": signature,
                    "calls": metadata.get("calls", []),
                    "score": (
                        round(match.score or 0.0, 3) if match.score is not None else 0.0
                    ),
                }
            )

        return results_list

    async def namespace_exists(self, namespace: str) -> bool:
        """Check if a namespace exists in Pinecone codebase index using the namespaces REST endpoint.

        Args:
            namespace: The namespace to check.

        Returns:
            True if namespace exists and has vectors, False otherwise.
        """
        if not self.is_available() or not self.pc or settings.pinecone_api_key is None:
            return False

        try:
            index_desc = self.pc.describe_index(settings.pinecone_codebase_index_name)
            index_host = index_desc.host

            url = f"https://{index_host}/namespaces/{namespace}"
            headers = {"Api-Key": settings.pinecone_api_key}
            async with httpx.AsyncClient() as client:  # nosec B113
                response = await client.get(url, headers=headers, timeout=10.0)
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Error checking namespace {namespace}: {e}")
            return False

    async def index_full_repo(
        self,
        repo: Repository,
        ref: str = "HEAD",
        delay_seconds: float = 0.0,
    ) -> IndexingResult:
        """Walk the entire repository tree at ref and index all supported files.

        Args:
            repo: GitHub Repository object
            ref: Git ref (commit SHA, branch, tag) to index
            delay_seconds: Delay in seconds between indexing individual files

        Returns:
            IndexingResult containing counts and skipped details
        """
        if not self.is_available():
            raise RuntimeError("Codebase index service is not available")

        owner = repo.owner.login.lower()
        repo_name = repo.name.lower()
        namespace = f"{owner}__{repo_name}"

        try:
            tree = repo.get_git_tree(ref, recursive=True)
            blobs = [element for element in tree.tree if element.type == "blob"]
        except Exception as e:
            raise RuntimeError(f"Failed to get Git tree: {e}") from e

        files_indexed = 0
        skipped_files = []

        for blob in blobs:
            if delay_seconds > 0.0:
                await asyncio.sleep(delay_seconds)
            path = blob.path
            lang = self._detect_language(path)
            if not lang:
                skipped_files.append({"file": path, "reason": "unsupported language"})
                continue

            try:
                github_file = repo.get_contents(path, ref=ref)
                if not github_file:
                    raise ValueError("Empty response from GitHub get_contents")
                if isinstance(github_file, list):
                    raise ValueError("Expected a file but received a directory listing")

                content_bytes = github_file.decoded_content
                content = content_bytes.decode("utf-8")
            except Exception as e:
                skipped_files.append(
                    {"file": path, "reason": f"failed to fetch content: {e}"}
                )
                continue

            try:
                chunks = self._parse_functions(content, lang)
            except Exception as e:
                skipped_files.append({"file": path, "reason": f"parse error: {e}"})
                continue

            if not chunks:
                skipped_files.append({"file": path, "reason": "no functions found"})
                continue

            try:
                await self._embed_and_upsert(chunks, namespace, path)
            except Exception as e:
                skipped_files.append(
                    {"file": path, "reason": f"failed to embed and upsert: {e}"}
                )
                continue

            files_indexed += 1

        return IndexingResult(files_indexed=files_indexed, files_skipped=skipped_files)


codebase_index_service = CodebaseIndexService()
