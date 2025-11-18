"""Output models for AI agent responses."""

# TODO: Import Literal from typing
# TODO: Import BaseModel and Field from pydantic

# TODO: Create ReviewComment model with fields:
#   - file_path: str (file being commented on)
#   - line_number: int (line number for comment)
#   - comment_body: str (the review comment text)
#   - severity: Literal["critical", "warning", "suggestion", "praise"]
#   - category: Literal["security", "performance", "maintainability", "best_practices",
#                       "code_quality", "documentation", "testing", "other"]
# TODO: Add @property methods:
#   - is_critical() -> bool
#   - is_positive() -> bool

# TODO: Create ReviewSummary model with fields:
#   - overall_assessment: str (overall assessment text)
#   - critical_issues: int (count, default=0)
#   - warnings: int (count, default=0)
#   - suggestions: int (count, default=0)
#   - praise_count: int (count, default=0)
#   - files_reviewed: int (number of files reviewed)
#   - recommendation: Literal["approve", "request_changes", "comment"]
#   - key_points: list[str] (key findings, default_factory=list)
# TODO: Add @property methods:
#   - total_issues() -> int
#   - has_critical_issues() -> bool

# TODO: Create CodeReviewResult model with fields:
#   - comments: list[ReviewComment] (all review comments, default_factory=list)
#   - summary: ReviewSummary (review summary)
#   - reviewed_files: list[str] (files reviewed, default_factory=list)
#   - skipped_files: list[str] (files skipped, default_factory=list)
#   - error_files: list[str] (files with errors, default_factory=list)
# TODO: Add @property methods:
#   - total_comments() -> int
#   - has_errors() -> bool
# TODO: Add method:
#   - format_summary_markdown() -> str (format summary as GitHub markdown)
