"""GitHub-specific type definitions."""

# TODO: Import Literal from typing
# TODO: Import BaseModel and Field from pydantic

# TODO: Create PRContext model with fields:
#   - number: int (PR number)
#   - title: str (PR title)
#   - description: str (PR body/description, default="")
#   - author: str (GitHub username)
#   - files_changed: int (total files changed)
#   - additions: int (total lines added)
#   - deletions: int (total lines deleted)
#   - commits: int (number of commits)
#   - labels: list[str] (PR labels, default_factory=list)
#   - base_branch: str (target branch, default="main")
#   - head_branch: str (source branch)

# TODO: Create FileDiff model with fields:
#   - filename: str (file path)
#   - status: Literal["added", "modified", "removed", "renamed"]
#   - additions: int (lines added)
#   - deletions: int (lines deleted)
#   - changes: int (total changes)
#   - patch: str (unified diff, default="")
#   - previous_filename: str | None (if renamed, default=None)
# TODO: Add @property methods:
#   - is_new_file() -> bool
#   - is_deleted_file() -> bool
#   - is_renamed_file() -> bool

# TODO: Create FileMetadata model with fields:
#   - path: str (file path)
#   - language: str | None (programming language)
#   - size: int (file size in bytes)
#   - sha: str (git SHA)
