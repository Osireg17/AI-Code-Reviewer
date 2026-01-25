"""Utility for tracking and fingerprinting review comments for delta analysis.

This module provides functions to:
1. Generate unique fingerprints for review comments (for deduplication)
2. Find resolved issues when code changes address previous feedback
3. Post acknowledgment replies to original threads when issues are fixed

Example fingerprint:
{
    "file": "src/foo.py",
    "line": 45,
    "issue_type": "naming",
    "pattern_hash": "abc123..."  # Hash of the code pattern mentioned
}
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CommentFingerprint:
    """Unique identifier for a review comment."""

    file_path: str
    line_number: int
    issue_type: str  # e.g., "naming", "style", "security", "performance"
    pattern_hash: str  # Hash of code pattern or identifier mentioned
    comment_id: int | None = None  # GitHub comment ID for thread replies
    original_text: str = ""  # For debugging/display

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        return {
            "file": self.file_path,
            "line": self.line_number,
            "issue_type": self.issue_type,
            "pattern_hash": self.pattern_hash,
            "comment_id": self.comment_id,
            "original_text": self.original_text[:200],  # Truncate for storage
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommentFingerprint":
        """Create from dictionary (from JSON storage)."""
        return cls(
            file_path=data.get("file", ""),
            line_number=data.get("line", 0),
            issue_type=data.get("issue_type", "unknown"),
            pattern_hash=data.get("pattern_hash", ""),
            comment_id=data.get("comment_id"),
            original_text=data.get("original_text", ""),
        )


@dataclass
class ResolvedIssue:
    """Represents an issue that appears to have been addressed."""

    fingerprint: CommentFingerprint
    resolution_type: str  # "fixed", "removed", "refactored"
    confidence: float = 0.8  # How confident we are this was actually resolved


# Common issue type patterns for classification
ISSUE_PATTERNS: dict[str, list[str]] = {
    "naming": [
        r"snake_case",
        r"camelCase",
        r"PascalCase",
        r"naming convention",
        r"variable name",
        r"function name",
        r"should be named",
        r"rename",
# Extract quoted identifiers (single or double quotes)
quote_matches = re.findall(r"['\"]([a-zA-Z_][a-zA-Z0-9_]*)['\"]", comment_body)
patterns.extend(quote_matches)
    "style": [
        r"indent",
        r"spacing",
        r"whitespace",
        r"line length",
        r"formatting",
        r"PEP\s*8",
        r"eslint",
        r"prettier",
    ],
    "security": [
        r"injection",
        r"XSS",
        r"SQL",
        r"sanitize",
        r"escape",
        r"OWASP",
        r"vulnerability",
        r"secret",
        r"credential",
    ],
    "performance": [
        r"O\(n",
        r"complexity",
        r"loop",
        r"cache",
        r"optimize",
        r"slow",
        r"efficient",
    ],
    "error_handling": [
        r"exception",
        r"error handling",
        r"try.*catch",
        r"raise",
        r"throw",
    ],
    "documentation": [
        r"docstring",
        r"comment",
        r"documentation",
        r"JSDoc",
        r"type hint",
    ],
}


def _classify_issue_type(comment_body: str) -> str:
    """Classify the issue type based on comment content."""
    comment_lower = comment_body.lower()

    for issue_type, patterns in ISSUE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, comment_lower, re.IGNORECASE):
                return issue_type

    return "general"


def _extract_code_pattern(comment_body: str) -> str:
    """Extract identifiable code patterns from the comment.

    Looks for:
    - Code in backticks: `foo_bar`
    - Suggested names: "should be named X"
    - Variable/function names mentioned
    """
    patterns = []

    # Extract backticked code
    backtick_matches = re.findall(r"`([^`]+)`", comment_body)
    patterns.extend(backtick_matches)

    # Extract quoted identifiers
    quote_matches = re.findall(r'"([a-zA-Z_][a-zA-Z0-9_]*)"', comment_body)
    patterns.extend(quote_matches)

    # Join patterns and hash
    pattern_str = "|".join(sorted(set(patterns)))
    return pattern_str


def _hash_pattern(pattern: str) -> str:
    """Generate a short hash of the pattern for fingerprinting."""
    if not pattern:
        return ""
    return hashlib.sha256(pattern.encode()).hexdigest()[:12]


def generate_issue_fingerprint(
    file_path: str,
    line_number: int,
    comment_body: str,
    comment_id: int | None = None,
) -> CommentFingerprint:
    """Generate a fingerprint for a review comment.

    Args:
        file_path: Path to the file the comment is on
        line_number: Line number of the comment
        comment_body: The full text of the review comment
        comment_id: Optional GitHub comment ID for thread replies

    Returns:
        CommentFingerprint that can be used for matching/deduplication
    """
    issue_type = _classify_issue_type(comment_body)
    code_pattern = _extract_code_pattern(comment_body)
    pattern_hash = _hash_pattern(code_pattern)

    return CommentFingerprint(
        file_path=file_path,
        line_number=line_number,
        issue_type=issue_type,
        pattern_hash=pattern_hash,
        comment_id=comment_id,
        original_text=comment_body,
    )


def find_resolved_issues(
    previous_comments: list[dict[str, Any]],
    changed_files: list[str],
    current_diffs: dict[str, str] | None = None,
) -> list[ResolvedIssue]:
    """Find issues from previous reviews that appear to be resolved.

    An issue is considered resolved if:
    1. The file was modified in the new changes
    2. The specific line/region was touched (if diff available)
    3. OR the file was deleted

    Args:
        previous_comments: List of comment fingerprint dicts from previous reviews
        changed_files: List of files changed in the current commit(s)
        current_diffs: Optional dict of file_path -> diff_content for detailed matching

    Returns:
        List of ResolvedIssue objects for issues that appear fixed
    """
    resolved = []

    for comment_data in previous_comments:
        try:
            fingerprint = CommentFingerprint.from_dict(comment_data)
        except Exception as e:
            logger.warning(f"Failed to parse comment fingerprint: {e}")
            continue

        file_path = fingerprint.file_path

        # Check if the file was changed
        if file_path not in changed_files:
            continue

        # If we have diffs, check if the specific region was touched
        if current_diffs and file_path in current_diffs:
            diff = current_diffs[file_path]
            line_touched = _is_line_in_diff_region(
                diff, fingerprint.line_number, tolerance=5
            )
            if not line_touched:
                continue

        # This issue was likely addressed
        resolved.append(
            ResolvedIssue(
                fingerprint=fingerprint,
                resolution_type="fixed",
                confidence=0.8 if current_diffs else 0.6,
            )
        )

    logger.info(f"Found {len(resolved)} potentially resolved issues")
    return resolved


def _is_line_in_diff_region(diff: str, target_line: int, tolerance: int = 5) -> bool:
    """Check if a line number falls within a changed region of a diff.

    Args:
        diff: The unified diff string
        target_line: The line number to check
        tolerance: How many lines away from the target still counts

    Returns:
        True if the line or nearby region was modified
    """
    # Parse @@ -old_start,old_count +new_start,new_count @@ lines
    hunk_pattern = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    for match in hunk_pattern.finditer(diff):
        new_start = int(match.group(1))
        new_count = int(match.group(2) or 1)

        # Check if target line falls within this hunk (with tolerance)
        hunk_start = new_start - tolerance
        hunk_end = new_start + new_count + tolerance

        if hunk_start <= target_line <= hunk_end:
            return True

    return False


async def post_resolution_acknowledgment(
    resolved_issues: list[ResolvedIssue],
    pr: Any,  # github.PullRequest.PullRequest
) -> int:
    """Post acknowledgment replies to threads where issues were resolved.

    Uses GitHub's reply-to-comment API to add a response in the original thread.

    Args:
        resolved_issues: List of resolved issues with comment_ids
        pr: GitHub PullRequest object

    Returns:
        Number of acknowledgments posted
    """
    posted_count = 0

    for resolved in resolved_issues:
        comment_id = resolved.fingerprint.comment_id
        if not comment_id:
            logger.debug(
                f"Skipping resolution acknowledgment - no comment_id for "
                f"{resolved.fingerprint.file_path}:{resolved.fingerprint.line_number}"
            )
            continue

        acknowledgment_text = (
            "✅ Thanks for addressing this! "
            f"The {resolved.fingerprint.issue_type} issue appears to be resolved."
        )

        try:
            # Use GitHub API to reply to the original thread
            # PyGithub supports this via create_review_comment with in_reply_to
            pr.create_review_comment(
                body=acknowledgment_text,
                commit=pr.head.sha,
                path=resolved.fingerprint.file_path,
                in_reply_to=comment_id,
            )
            posted_count += 1
            logger.info(
                f"Posted resolution acknowledgment for comment {comment_id} "
                f"on {resolved.fingerprint.file_path}"
            )
        except Exception as e:
            logger.warning(f"Failed to post resolution acknowledgment: {e}")

    return posted_count


def build_comments_for_storage(
    comments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert review comments to fingerprint format for database storage.

    Args:
        comments: List of comment dicts with file_path, line_number, comment_body keys

    Returns:
        List of fingerprint dicts ready for storage in ReviewState.previous_comments
    """
    fingerprints = []

    for comment in comments:
        try:
            fingerprint = generate_issue_fingerprint(
                file_path=comment.get("file_path", ""),
                line_number=comment.get("line_number", 0),
                comment_body=comment.get("comment_body", comment.get("body", "")),
                comment_id=comment.get("comment_id"),
            )
            fingerprints.append(fingerprint.to_dict())
        except Exception as e:
            logger.warning(f"Failed to generate fingerprint for comment: {e}")

    return fingerprints
