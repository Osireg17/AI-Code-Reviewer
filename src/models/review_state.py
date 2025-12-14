"""SQLAlchemy model for tracking PR review state."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.conversation import Base


class ReviewState(Base):
    """
    Tracks the review state for each pull request.

    Used to implement incremental reviews - only reviewing files changed
    since the last review instead of re-reviewing the entire PR on each commit.
    """

    __tablename__ = "review_states"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # GitHub identifiers
    repo_full_name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, comment="e.g., 'owner/repo'"
    )
    pr_number: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="Pull request number"
    )

    # Review state tracking
    last_reviewed_commit_sha: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        comment="SHA of the last commit that was reviewed (40 char Git SHA)",
    )
    initial_review_completed: Mapped[bool] = mapped_column(
        Boolean,  # SQLite doesn't have native boolean, uses 0/1
        nullable=False,
        default=False,
        comment="Whether the initial full PR review has been completed",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="When review tracking started for this PR",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="Last time this PR was reviewed",
    )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"<ReviewState(id={self.id}, "
            f"repo={self.repo_full_name}, "
            f"pr={self.pr_number}, "
            f"last_sha={self.last_reviewed_commit_sha[:7]}, "
            f"initial_complete={self.initial_review_completed})>"
        )

    def update_review_state(
        self, new_commit_sha: str, mark_initial_complete: bool = False
    ) -> None:
        """
        Update the review state after reviewing new commits.

        Args:
            new_commit_sha: The latest commit SHA that was just reviewed
            mark_initial_complete: Whether to mark initial review as completed
        """
        self.last_reviewed_commit_sha = new_commit_sha
        if mark_initial_complete:
            self.initial_review_completed = True
        self.updated_at = datetime.now(timezone.utc)
