"""Unit tests for comment state serialization/parsing."""

from src.utils.comment_state import (
    build_state_for_review,
    parse_state_from_comment,
    serialize_state_to_comment,
    strip_state_from_comment,
)


class TestSerializeStateToComment:
    """Tests for serialize_state_to_comment function."""

    def test_serializes_basic_state(self) -> None:
        """Test basic state serialization."""
        state = {
            "last_reviewed_sha": "abc123def456",  # pragma: allowlist secret
            "reviewed_files": ["src/foo.py"],
            "comments": [],
        }

        result = serialize_state_to_comment(state)

        assert "<!-- AI-REVIEWER-STATE" in result
        assert "-->" in result
        assert "abc123def456" in result  # pragma: allowlist secret
        assert "src/foo.py" in result

    def test_serializes_complex_state(self) -> None:
        """Test serialization with comments and multiple files."""
        state = {
            "last_reviewed_sha": "xyz789",
            "reviewed_files": ["src/a.py", "src/b.py", "src/c.py"],
            "comments": [
                {"file": "src/a.py", "line": 10, "issue": "naming"},
                {"file": "src/b.py", "line": 20, "issue": "style"},
            ],
        }

        result = serialize_state_to_comment(state)

        assert "xyz789" in result
        assert "src/a.py" in result
        assert "src/b.py" in result
        assert "src/c.py" in result
        assert '"line": 10' in result
        assert '"line": 20' in result

    def test_returns_empty_string_on_error(self) -> None:
        """Test graceful handling of non-serializable objects."""

        # Create an object that can't be JSON serialized
        class NonSerializable:
            pass

        state = {"bad_object": NonSerializable()}

        result = serialize_state_to_comment(state)

        assert result == ""


class TestParseStateFromComment:
    """Tests for parse_state_from_comment function."""

    def test_parses_embedded_state(self) -> None:
        """Test parsing state from comment body."""
        body = """
## Review Summary

This looks good!

<!-- AI-REVIEWER-STATE
{
  "last_reviewed_sha": "abc123",
  "reviewed_files": ["src/foo.py"],
  "comments": []
}
-->
"""
        result = parse_state_from_comment(body)

        assert result is not None
        assert result["last_reviewed_sha"] == "abc123"
        assert result["reviewed_files"] == ["src/foo.py"]
        assert result["comments"] == []

    def test_returns_none_for_no_state(self) -> None:
        """Test returns None when no state embedded."""
        body = "## Review Summary\n\nThis looks good!"

        result = parse_state_from_comment(body)

        assert result is None

    def test_returns_none_for_empty_body(self) -> None:
        """Test returns None for empty body."""
        result = parse_state_from_comment("")
        assert result is None

        result = parse_state_from_comment(None)
        assert result is None

    def test_returns_none_for_invalid_json(self) -> None:
        """Test returns None for malformed JSON."""
        body = """
<!-- AI-REVIEWER-STATE
{this is not valid json}
-->
"""
        result = parse_state_from_comment(body)

        assert result is None

    def test_returns_none_for_non_dict_json(self) -> None:
        """Test returns None when JSON is not a dict."""
        body = """
<!-- AI-REVIEWER-STATE
["this", "is", "an", "array"]
-->
"""
        result = parse_state_from_comment(body)

        assert result is None

    def test_handles_case_insensitive_marker(self) -> None:
        """Test marker matching is case-insensitive."""
        body = """
<!-- ai-reviewer-state
{
  "last_reviewed_sha": "test123"
}
-->
"""
        result = parse_state_from_comment(body)

        assert result is not None
        assert result["last_reviewed_sha"] == "test123"


class TestStripStateFromComment:
    """Tests for strip_state_from_comment function."""

    def test_strips_embedded_state(self) -> None:
        """Test removing state from comment body."""
        body = """## Review Summary

This looks good!

<!-- AI-REVIEWER-STATE
{
  "last_reviewed_sha": "abc123"
}
-->"""
        result = strip_state_from_comment(body)

        assert "AI-REVIEWER-STATE" not in result
        assert "abc123" not in result
        assert "Review Summary" in result
        assert "This looks good!" in result

    def test_returns_unchanged_if_no_state(self) -> None:
        """Test returns body unchanged when no state present."""
        body = "## Review Summary\n\nThis looks good!"

        result = strip_state_from_comment(body)

        assert result == body

    def test_handles_empty_body(self) -> None:
        """Test handles empty/None body."""
        assert strip_state_from_comment("") == ""
        assert strip_state_from_comment(None) is None


class TestBuildStateForReview:
    """Tests for build_state_for_review function."""

    def test_builds_basic_state(self) -> None:
        """Test building state with required fields."""
        state = build_state_for_review(
            last_reviewed_sha="abc123",
            reviewed_files=["src/foo.py", "src/bar.py"],
        )

        assert state["last_reviewed_sha"] == "abc123"
        assert state["reviewed_files"] == ["src/foo.py", "src/bar.py"]
        assert state["comments"] == []
        assert state["version"] == "1.0"

    def test_builds_state_with_comments(self) -> None:
        """Test building state with comment metadata."""
        comments = [
            {"file": "src/foo.py", "line": 10, "issue": "naming"},
        ]

        state = build_state_for_review(
            last_reviewed_sha="xyz789",
            reviewed_files=["src/foo.py"],
            comments=comments,
        )

        assert state["comments"] == comments


class TestRoundTrip:
    """Integration tests for serialize -> parse round trip."""

    def test_state_survives_round_trip(self) -> None:
        """Test state can be serialized and parsed back."""
        original_state = build_state_for_review(
            last_reviewed_sha="abc123def456789",  # pragma: allowlist secret
            reviewed_files=["src/foo.py", "src/bar.js"],
            comments=[
                {"file": "src/foo.py", "line": 42, "issue": "snake_case"},
            ],
        )

        serialized = serialize_state_to_comment(original_state)
        parsed = parse_state_from_comment(serialized)

        assert parsed is not None
        assert parsed["last_reviewed_sha"] == original_state["last_reviewed_sha"]
        assert parsed["reviewed_files"] == original_state["reviewed_files"]
        assert parsed["comments"] == original_state["comments"]
        assert parsed["version"] == original_state["version"]

    def test_state_survives_embedding_in_comment(self) -> None:
        """Test state survives being embedded in a larger comment."""
        state = build_state_for_review(
            last_reviewed_sha="test123",
            reviewed_files=["test.py"],
        )

        # Simulate a real summary comment with embedded state
        full_comment = f"""## Review Summary

Overall: Looks good!

**Files reviewed:** 1
**Issues found:** 0

{serialize_state_to_comment(state)}"""

        parsed = parse_state_from_comment(full_comment)

        assert parsed is not None
        assert parsed["last_reviewed_sha"] == "test123"
