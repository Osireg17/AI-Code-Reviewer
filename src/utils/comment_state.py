"""Utility for embedding/extracting review state in GitHub comment metadata.

This module provides functions to serialize and deserialize review state
as hidden HTML comments within summary comments. This serves as a backup
for the database state and aids debugging/recovery.

Example format:
<!-- AI-REVIEWER-STATE
{
  "last_reviewed_sha": "abc123...",
  "reviewed_files": ["src/foo.py"],
  "comments": [{"file": "src/foo.py", "line": 45, "issue": "snake_case"}]
}
-->
"""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Marker tags for state embedding
STATE_START_MARKER = "<!-- AI-REVIEWER-STATE"
STATE_END_MARKER = "-->"

STATE_PATTERN = re.compile(
    r"<!--\s*AI-REVIEWER-STATE\s*\r?\n(.*?)\r?\n\s*-->",
    re.DOTALL | re.IGNORECASE,
)
STATE_PATTERN = re.compile(
    r"<!--\s*AI-REVIEWER-STATE\s*\n(.*?)\n\s*-->",
    re.DOTALL | re.IGNORECASE,
)


def serialize_state_to_comment(state: dict[str, Any]) -> str:
    """
    Serialize review state dictionary to hidden HTML comment format.

    Args:
        state: Dictionary containing review state data with keys like:
            - last_reviewed_sha: str
            - reviewed_files: list[str]
            - comments: list[dict] with file, line, issue keys

    Returns:
        HTML comment string that can be appended to summary comment body
    """
    try:
        # Pretty-print JSON for readability in GitHub source view
        json_str = json.dumps(state, indent=2, sort_keys=True)
        return f"\n\n{STATE_START_MARKER}\n{json_str}\n{STATE_END_MARKER}"
    except (TypeError, ValueError) as e:
        logger.error(f"Failed to serialize state to comment: {e}")
        # Return empty string on error - state backup is non-critical
        return ""


def parse_state_from_comment(body: str) -> dict[str, Any] | None:
    """
    Parse review state from comment body containing hidden HTML metadata.

    Args:
        body: The full comment body text that may contain embedded state

    Returns:
        Parsed state dictionary if found and valid, None otherwise
    """
    if not body:
        return None

    match = STATE_PATTERN.search(body)
    if not match:
        logger.debug("No embedded state found in comment body")
        return None

    try:
        json_str = match.group(1).strip()
        state = json.loads(json_str)

        # Validate expected structure
        if not isinstance(state, dict):
            logger.warning(f"Parsed state is not a dict: {type(state)}")
            return None

        return state
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse embedded state JSON: {e}")
        return None


def strip_state_from_comment(body: str) -> str:
    """
    Remove embedded state metadata from comment body.

    Useful when displaying the comment to users or comparing content.

    Args:
        body: The full comment body text that may contain embedded state

    Returns:
        Comment body with state metadata removed
    """
    if not body:
        return body

    # Remove the state block including surrounding whitespace
    cleaned = STATE_PATTERN.sub("", body)
    return cleaned.strip()


def build_state_for_review(
    last_reviewed_sha: str,
    reviewed_files: list[str],
    comments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Build a standardized state dictionary for embedding.

    Args:
        last_reviewed_sha: SHA of the commit that was just reviewed
        reviewed_files: List of file paths that were reviewed
        comments: Optional list of comment metadata dicts

    Returns:
        State dictionary ready for serialization
    """
    return {
        "last_reviewed_sha": last_reviewed_sha,
        "reviewed_files": reviewed_files,
        "comments": comments or [],
        "version": "1.0",  # For future schema migrations
    }
