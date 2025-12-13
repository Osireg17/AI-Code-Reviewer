"""Dependency injection types for Pydantic AI agents."""

from typing import Any

import httpx
from github import Github
from github.PullRequest import PullRequest
from github.Repository import Repository
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator


class ReviewDependencies(BaseModel):
    """Dependencies for the code review agent.

    This model holds all runtime dependencies needed by the Pydantic AI agent
    to perform code reviews on GitHub pull requests.
    """

    github_client: Github
    http_client: httpx.AsyncClient
    pr_number: int
    repo_full_name: str

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
