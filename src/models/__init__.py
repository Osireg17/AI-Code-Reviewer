"""Data models for AI Code Reviewer."""

from .dependencies import ReviewDependencies
from .github_types import FileDiff, PRContext
from .outputs import CodeReviewResult, ReviewComment, ReviewSummary

__all__ = [
    "ReviewDependencies",
    "PRContext",
    "FileDiff",
    "CodeReviewResult",
    "ReviewComment",
    "ReviewSummary",
]
