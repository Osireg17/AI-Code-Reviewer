"""GitHub-specific type definitions."""

from typing import Literal

from pydantic import BaseModel, Field


class PRContext(BaseModel):
    """Pull request context and metadata.

    Contains all relevant information about a pull request needed
    for code review analysis.
    """

    number: int
    title: str
    description: str = ""
    author: str
    files_changed: int
    additions: int
    deletions: int
    commits: int
    labels: list[str] = Field(default_factory=list)
    base_branch: str = "main"
    head_branch: str


class FileDiff(BaseModel):
    """File diff information from a pull request.

    Represents changes to a single file in a PR, including the diff patch
    and metadata about additions/deletions.
    """

    filename: str
    status: Literal["added", "modified", "removed", "renamed"]
    additions: int
    deletions: int
    changes: int
    patch: str = ""
    previous_filename: str | None = None

    @property
    def is_new_file(self) -> bool:
        """Check if this is a newly added file.

        Returns:
            True if the file status is "added"
        """
        return self.status == "added"

    @property
    def is_deleted_file(self) -> bool:
        """Check if this file was deleted.

        Returns:
            True if the file status is "removed"
        """
        return self.status == "removed"

    @property
    def is_renamed_file(self) -> bool:
        """Check if this file was renamed.

        Returns:
            True if the file status is "renamed"
        """
        return self.status == "renamed"


class FileMetadata(BaseModel):
    """Metadata about a file in the repository.

    Contains information about a file's properties like language,
    size, and git SHA.
    """

    path: str
    language: str | None
    size: int
    sha: str
