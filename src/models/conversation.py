"""SQLAlchemy model for conversation threads on GitHub PRs."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class ConversationThread(Base):
    """
    Tracks multi-turn conversation threads on GitHub PR comments.

    Each thread represents a discussion between the bot and developers
    on a specific inline comment or review summary.
    """

    __tablename__ = "conversation_threads"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # GitHub identifiers for tracking
    repo_full_name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, comment="e.g., 'owner/repo'"
    )
    pr_number: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="Pull request number"
    )
    comment_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        unique=True,
        index=True,
        comment="GitHub comment ID that started the thread",
    )

    # Thread metadata
    thread_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type: 'inline_comment' or 'summary_review'",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="active",
        comment="Status: 'active', 'resolved', 'abandoned'",
    )

    # Conversation content stored as JSONB for flexibility
    # Structure: [{"role": "bot"|"developer", "content": str, "timestamp": str, "comment_id": int}, ...]
    thread_messages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: [],
        comment="Array of message objects in chronological order",
    )

    # Original context for reference
    original_file_path: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="File path for inline comments"
    )
    original_line_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Line number for inline comments"
    )
    original_suggestion: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Bot's original suggestion/comment"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="Thread creation timestamp",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="Last message timestamp",
    )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"<ConversationThread(id={self.id}, "
            f"repo={self.repo_full_name}, "
            f"pr={self.pr_number}, "
            f"comment={self.comment_id}, "
            f"status={self.status})>"
        )

    def add_message(
        self, role: str, content: str, comment_id: int | None = None
    ) -> None:
        """
        Add a new message to the conversation thread.

        Args:
            role: Either 'bot' or 'developer'
            content: Message content
            comment_id: GitHub comment ID (optional for internal tracking)
        """
        if self.thread_messages is None:
            self.thread_messages = []

        message: dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if comment_id is not None:
            message["comment_id"] = comment_id

        # Re-assign list to ensure SQLAlchemy detects the change
        # (In-place append on JSON types is not always tracked)
        messages = list(self.thread_messages)
        messages.append(message)
        self.thread_messages = messages

        self.updated_at = datetime.now(timezone.utc)

    def get_context_for_llm(self) -> list[dict[str, str]]:
        """
        Format thread messages for LLM context.

        Returns:
            List of messages in OpenAI chat format: [{"role": "assistant"|"user", "content": str}, ...]
        """
        if not self.thread_messages:
            return []

        formatted_messages = []
        for msg in self.thread_messages:
            # Map bot -> assistant, developer -> user
            llm_role = "assistant" if msg["role"] == "bot" else "user"
            formatted_messages.append({"role": llm_role, "content": msg["content"]})

        return formatted_messages

    def mark_resolved(self) -> None:
        """Mark the conversation thread as resolved."""
        self.status = "resolved"
        self.updated_at = datetime.now(timezone.utc)

    def mark_abandoned(self) -> None:
        """Mark the conversation thread as abandoned (no activity)."""
        self.status = "abandoned"
        self.updated_at = datetime.now(timezone.utc)
