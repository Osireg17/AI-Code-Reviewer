"""Dependency injection types for Pydantic AI agents."""

from typing import Any

import httpx
from github import Github
from github.PullRequest import PullRequest
from github.Repository import Repository
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationInfo,
    field_validator,
)
from sqlalchemy.orm import Session


class ReviewDependencies(BaseModel):
    """Dependencies for the code review agent.

    This model holds all runtime dependencies needed by the Pydantic AI agent
    to perform code reviews on GitHub pull requests.
    """

    github_client: Github
    http_client: httpx.AsyncClient
    pr_number: int
    repo_full_name: str
    db_session: Session | None = Field(default=None, exclude=True)
    is_incremental_review: bool = Field(default=False, exclude=True)
    base_commit_sha: str | None = Field(default=None, exclude=True)

    # Private cache for tool results (not serialized)
    _cache: dict[str, Any] = PrivateAttr(default_factory=dict)

    # Cache for GitHub API objects (not serialized)
    repo: Repository | None = Field(default=None, exclude=True)
    pr: PullRequest | None = Field(default=None, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("repo_full_name")
    @classmethod
    def validate_repo_full_name(cls, v: str) -> str:
        """Validate repo_full_name is in 'owner/repo' format."""
        if not v or not v.strip():
            raise ValueError("repo_full_name cannot be empty")

        if v.count("/") != 1:
            raise ValueError(
                f"repo_full_name must be in 'owner/repo' format, got: '{v}'"
            )

        parts = v.split("/")
        if not parts[0] or not parts[1]:
            raise ValueError(
                f"repo_full_name must have non-empty owner and repo parts, got: '{v}'"
            )

        return v

    @field_validator("pr_number")
    @classmethod
    def validate_pr_number(cls, v: int) -> int:
        """Validate pr_number is positive."""
        if v <= 0:
            raise ValueError(f"pr_number must be positive (> 0), got: {v}")

        return v


class ConversationDependencies(BaseModel):
    """
    Dependencies for the conversation agent.

    === CONTEXT ===
    Purpose: Hold all context needed for bot to respond to user questions about code reviews
    Used by: conversation_agent.py
    Reference: Similar to ReviewDependencies but focused on conversations

    === DATA / STATE ===
    This model captures:
    - Conversation history (previous messages in thread)
    - User's current question
    - Original bot suggestion and code context
    - Current code state (may have changed since review)
    - GitHub API objects for fetching additional context

    Lifecycle: Created once per conversation reply, passed to agent

    === FIELDS ===
    Conversation Context:
    - conversation_history: List of previous messages (from ConversationThread.get_context_for_llm())
    - user_question: Current question/comment from developer
    - original_bot_comment: Bot's original review comment that started thread

    Code Context:
    - file_path: File being discussed
    - line_number: Line number in file (1-indexed)
    - original_code_snippet: Code when bot originally reviewed (may be None if deleted)
    - current_code_snippet: Current code at PR head (may differ from original)
    - code_changed: Boolean flag - true if code differs between commits

    GitHub Context:
    - pr_number: Pull request number
    - repo_name: Repository full name (owner/repo)
    - repo: Repository object (for fetching code)
    - pr: PullRequest object (for posting replies)
    - github_client: Github client for API calls

    Database:
    - db_session: SQLAlchemy session (for updating ConversationThread)
    """

    # Conversation context
    conversation_history: list[dict[str, str]] = Field(
        default_factory=list,
        description="Previous messages in LLM format: [{'role': 'user'|'assistant', 'content': str}]",
    )
    user_question: str = Field(description="Current question/comment from developer")
    original_bot_comment: str | None = Field(
        default=None,
        description="Bot's original review comment that started this thread",
    )

    # Code context
    file_path: str = Field(description="Path to file being discussed")
    line_number: int = Field(description="Line number in file (1-indexed)")
    original_code_snippet: str | None = Field(
        default=None,
        description="Code snippet when bot originally reviewed (may be None if file deleted)",
    )
    current_code_snippet: str | None = Field(
        default=None,
        description="Current code snippet at PR head (may differ from original)",
    )
    code_changed: bool = Field(
        default=False,
        description="True if code has been modified since original review",
    )

    # GitHub context
    pr_number: int = Field(description="Pull request number")
    repo_name: str = Field(description="Repository full name (owner/repo format)")
    repo: Repository | None = Field(
        default=None,
        exclude=True,
        description="GitHub Repository object for fetching code",
    )
    pr: PullRequest | None = Field(
        default=None,
        exclude=True,
        description="GitHub PullRequest object for posting replies",
    )
    github_client: Github | None = Field(
        default=None,
        exclude=True,
        description="GitHub client for API calls",
    )

    # Database
    db_session: Session | None = Field(
        default=None,
        exclude=True,
        description="SQLAlchemy session for updating conversation thread",
    )

    # Private cache for tool results
    _cache: dict[str, Any] = PrivateAttr(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("repo_name")
    @classmethod
    def validate_repo_name(cls, v: str) -> str:
        """
        Validate repo_name is in 'owner/repo' format.

        === LOGIC ===
        CHECK repo_name is not empty
        CHECK contains exactly one '/'
        CHECK both owner and repo parts are non-empty
        RETURN validated value

        === EDGE CASES ===
        - Empty string: Raise ValueError
        - No '/': Raise ValueError
        - Multiple '/': Raise ValueError
        - Empty owner or repo: Raise ValueError
        """
        if not v or not v.strip():
            raise ValueError("repo_name cannot be empty")

        if v.count("/") != 1:
            raise ValueError(f"repo_name must be in 'owner/repo' format, got: '{v}'")

        owner, repo = v.split("/")
        if not owner or not repo:
            raise ValueError(
                f"repo_name must have non-empty owner and repo parts, got: '{v}'"
            )

        return v

    @field_validator("pr_number", "line_number")
    @classmethod
    def validate_positive_int(cls, v: int, info: ValidationInfo) -> int:
        """
        Validate integer fields are positive.

        === LOGIC ===
        CHECK value is greater than 0
        IF not THEN raise ValueError with field name
        RETURN validated value
        """
        if v <= 0:
            raise ValueError(f"{info.field_name} must be positive (> 0), got: {v}")
        return v

    @field_validator("user_question")
    @classmethod
    def validate_user_question_not_empty(cls, v: str) -> str:
        """
        Ensure user question is not empty.

        === LOGIC ===
        STRIP whitespace
        CHECK length > 0
        IF empty THEN raise ValueError
        RETURN stripped value

        === EDGE CASES ===
        - Whitespace only: Raise ValueError
        - Empty string: Raise ValueError
        - Very long question (>5000 chars): Log warning but allow
        """
        v = v.strip()
        if not v:
            raise ValueError("user_question cannot be empty")
        return v
