"""Output models for AI agent responses."""

from typing import Literal

from pydantic import BaseModel, Field


class ReviewComment(BaseModel):
    """A single code review comment.

    Represents an inline comment on a specific file and line,
    categorized by severity and type.
    """

    file_path: str
    line_number: int
    comment_body: str
    severity: Literal["critical", "warning", "suggestion", "praise"]
    category: Literal[
        "security",
        "performance",
        "maintainability",
        "best_practices",
        "code_quality",
        "documentation",
        "testing",
        "other",
    ]

    @property
    def is_critical(self) -> bool:
        """Check if this comment is marked as critical.

        Returns:
            True if severity is "critical"
        """
        return self.severity == "critical"

    @property
    def is_positive(self) -> bool:
        """Check if this comment is positive feedback.

        Returns:
            True if severity is "praise"
        """
        return self.severity == "praise"


class ReviewSummary(BaseModel):
    """Summary of the code review.

    Aggregates statistics about the review and provides an overall
    assessment with recommendations.
    """

    overall_assessment: str
    critical_issues: int = 0
    warnings: int = 0
    suggestions: int = 0
    praise_count: int = 0
    files_reviewed: int
    recommendation: Literal["approve", "request_changes", "comment"]
    key_points: list[str] = Field(default_factory=list)

    @property
    def total_issues(self) -> int:
        """Calculate total number of issues (critical + warnings + suggestions).

        Returns:
            Sum of critical issues, warnings, and suggestions
        """
        return self.critical_issues + self.warnings + self.suggestions

    @property
    def has_critical_issues(self) -> bool:
        """Check if there are any critical issues.

        Returns:
            True if critical_issues > 0
        """
        return self.critical_issues > 0


class CodeReviewResult(BaseModel):
    """Complete code review result.

    Contains all review comments, summary, and metadata about
    which files were reviewed or skipped.
    """

    comments: list[ReviewComment] = Field(default_factory=list)
    summary: ReviewSummary
    reviewed_files: list[str] = Field(default_factory=list)
    skipped_files: list[str] = Field(default_factory=list)
    error_files: list[str] = Field(default_factory=list)

    @property
    def total_comments(self) -> int:
        """Get the total number of comments.

        Returns:
            The length of the comments list
        """
        return len(self.comments)

    @property
    def has_errors(self) -> bool:
        """Check if any files had errors during review.

        Returns:
            True if error_files is not empty
        """
        return len(self.error_files) > 0

    def format_summary_markdown(self) -> str:
        """Format the review summary as GitHub-flavored markdown.

        Returns:
            Formatted markdown string suitable for posting to GitHub
        """
        lines = ["# Code Review Summary\n"]

        # Overall assessment
        lines.append(f"## Overall Assessment\n\n{self.summary.overall_assessment}\n")

        # Recommendation
        recommendation_emoji = {
            "approve": ":white_check_mark:",
            "request_changes": ":x:",
            "comment": ":speech_balloon:",
        }
        emoji = recommendation_emoji.get(self.summary.recommendation, "")
        recommendation_text = self.summary.recommendation.replace("_", " ").title()
        lines.append(f"## Recommendation: {emoji} {recommendation_text}\n")

        # Statistics
        lines.append("## Statistics\n")
        lines.append(f"- **Files Reviewed:** {self.summary.files_reviewed}")
        lines.append(f"- **Total Comments:** {self.total_comments}")
        lines.append(f"- **Critical Issues:** {self.summary.critical_issues}")
        lines.append(f"- **Warnings:** {self.summary.warnings}")
        lines.append(f"- **Suggestions:** {self.summary.suggestions}")
        lines.append(f"- **Praise:** {self.summary.praise_count}\n")

        # Key points
        if self.summary.key_points:
            lines.append("## Key Points\n")
            for point in self.summary.key_points:
                lines.append(f"- {point}")
            lines.append("")

        # File breakdown
        if self.skipped_files:
            lines.append("## Skipped Files\n")
            for file in self.skipped_files:
                lines.append(f"- `{file}`")
            lines.append("")

        if self.error_files:
            lines.append("## Files with Errors\n")
            for file in self.error_files:
                lines.append(f"- `{file}`")
            lines.append("")

        return "\n".join(lines)
