"""Data models for AI Code Reviewer."""

from .conversation import ConversationThread
from .dependencies import ReviewDependencies
from .github_types import FileDiff, PRContext
from .outputs import CodeReviewResult, ReviewComment, ReviewSummary
from .review_state import ReviewState

__all__ = [
    "ReviewDependencies",
    "PRContext",
    "FileDiff",
    "CodeReviewResult",
    "ReviewComment",
    "ReviewSummary",
    "ConversationThread",
    "ReviewState",
]
