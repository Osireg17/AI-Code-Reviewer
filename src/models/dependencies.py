"""Dependency injection types for Pydantic AI agents."""

# TODO: Import dataclass from dataclasses
# TODO: Import Github from github
# TODO: Import httpx

# TODO: Create ReviewDependencies dataclass with fields:
#   - github_client: Github (authenticated GitHub API client)
#   - http_client: httpx.AsyncClient (for async HTTP requests)
#   - pr_number: int (the PR number being reviewed)
#   - repo_full_name: str (format: "owner/repo")

# TODO: Add __post_init__ method to validate:
#   - repo_full_name contains "/" and is not empty
#   - pr_number is positive (> 0)
#   - Raise ValueError with descriptive messages if invalid
