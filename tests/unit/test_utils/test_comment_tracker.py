"""Unit tests for comment tracking and fingerprinting."""

import pytest

from src.utils.comment_tracker import (
    CommentFingerprint,
    _classify_issue_type,
    _extract_code_pattern,
    _hash_pattern,
    _is_line_in_diff_region,
    build_comments_for_storage,
    find_resolved_issues,
    generate_issue_fingerprint,
)


class TestCommentFingerprint:
    """Tests for CommentFingerprint dataclass."""

    def test_to_dict(self):
        """Test converting fingerprint to dict."""
        fp = CommentFingerprint(
            file_path="src/foo.py",
            line_number=42,
            issue_type="naming",
            pattern_hash="abc123",
            comment_id=12345,
            original_text="Variable should use snake_case",
        )

        result = fp.to_dict()

        assert result["file"] == "src/foo.py"
        assert result["line"] == 42
        assert result["issue_type"] == "naming"
        assert result["pattern_hash"] == "abc123"
        assert result["comment_id"] == 12345
        assert "snake_case" in result["original_text"]

    def test_to_dict_truncates_long_text(self):
        """Test that original_text is truncated for storage."""
        long_text = "x" * 500  # Longer than 200 chars
        fp = CommentFingerprint(
            file_path="test.py",
            line_number=1,
            issue_type="general",
            pattern_hash="",
            original_text=long_text,
        )

        result = fp.to_dict()

        assert len(result["original_text"]) == 200

    def test_from_dict(self):
        """Test creating fingerprint from dict."""
        data = {
            "file": "src/bar.js",
            "line": 100,
            "issue_type": "security",
            "pattern_hash": "xyz789",
            "comment_id": 67890,
            "original_text": "Potential XSS vulnerability",
        }

        fp = CommentFingerprint.from_dict(data)

        assert fp.file_path == "src/bar.js"
        assert fp.line_number == 100
        assert fp.issue_type == "security"
        assert fp.pattern_hash == "xyz789"
        assert fp.comment_id == 67890
        assert fp.original_text == "Potential XSS vulnerability"

    def test_from_dict_with_missing_fields(self):
        """Test graceful handling of missing dict fields."""
        data = {"file": "test.py"}  # Minimal data

        fp = CommentFingerprint.from_dict(data)

        assert fp.file_path == "test.py"
        assert fp.line_number == 0
        assert fp.issue_type == "unknown"
        assert fp.pattern_hash == ""


class TestClassifyIssueType:
    """Tests for _classify_issue_type function."""

    @pytest.mark.parametrize(
        "comment,expected_type",
        [
            ("Variable should use snake_case", "naming"),
            ("Function name uses camelCase incorrectly", "naming"),
            ("Please rename this variable", "naming"),
            ("Inconsistent indentation", "style"),
            ("Line length exceeds limit per PEP 8", "style"),
            ("Fix spacing issues", "style"),
            ("Potential SQL injection vulnerability", "security"),
            ("XSS risk in user input", "security"),
            ("Sanitize this input", "security"),
            ("O(n^2) complexity could be optimized", "performance"),
            ("This loop is slow and should be optimized", "performance"),
            ("Missing exception handling", "error_handling"),
            ("Add try-catch block", "error_handling"),
            ("Missing docstring", "documentation"),
            ("Add type hints", "documentation"),
            ("Looks good to me", "general"),
        ],
    )
    def test_classifies_issue_types(self, comment, expected_type):
        """Test issue type classification for various comments."""
        result = _classify_issue_type(comment)
        assert result == expected_type


class TestExtractCodePattern:
    """Tests for _extract_code_pattern function."""

    def test_extracts_backticked_code(self):
        """Test extraction of code in backticks."""
        comment = "Variable `user_name` should be `userName`"

        result = _extract_code_pattern(comment)

        assert "user_name" in result
        assert "userName" in result

    def test_extracts_quoted_identifiers(self):
        """Test extraction of quoted identifiers."""
        comment = 'Rename "foo_bar" to "fooBar"'

        result = _extract_code_pattern(comment)

        assert "foo_bar" in result
        assert "fooBar" in result

    def test_handles_no_patterns(self):
        """Test handling of comments with no extractable patterns."""
        comment = "This looks good!"

        result = _extract_code_pattern(comment)

        assert result == ""


class TestHashPattern:
    """Tests for _hash_pattern function."""

    def test_creates_short_hash(self):
        """Test hash is created and truncated."""
        result = _hash_pattern("some_pattern")

        assert len(result) == 12
        assert result.isalnum()

    def test_consistent_hashing(self):
        """Test same input produces same hash."""
        result1 = _hash_pattern("test_pattern")
        result2 = _hash_pattern("test_pattern")

        assert result1 == result2

    def test_different_input_different_hash(self):
        """Test different inputs produce different hashes."""
        result1 = _hash_pattern("pattern_a")
        result2 = _hash_pattern("pattern_b")

        assert result1 != result2

    def test_empty_pattern(self):
        """Test empty pattern returns empty string."""
        result = _hash_pattern("")

        assert result == ""


class TestGenerateIssueFingerprint:
    """Tests for generate_issue_fingerprint function."""

    def test_generates_complete_fingerprint(self):
        """Test generating a complete fingerprint."""
        fp = generate_issue_fingerprint(
            file_path="src/app.py",
            line_number=42,
            comment_body="Variable `user_data` should use snake_case",
            comment_id=12345,
        )

        assert fp.file_path == "src/app.py"
        assert fp.line_number == 42
        assert fp.issue_type == "naming"
        assert fp.comment_id == 12345
        assert "snake_case" in fp.original_text
        # Pattern hash should be set from extracted `user_data`
        assert fp.pattern_hash != ""

    def test_generates_fingerprint_without_comment_id(self):
        """Test fingerprint generation without GitHub comment ID."""
        fp = generate_issue_fingerprint(
            file_path="src/utils.js",
            line_number=100,
            comment_body="Potential XSS vulnerability here",
        )

        assert fp.file_path == "src/utils.js"
        assert fp.line_number == 100
        assert fp.issue_type == "security"
        assert fp.comment_id is None


class TestIsLineInDiffRegion:
    """Tests for _is_line_in_diff_region function."""

    def test_line_in_diff_hunk(self):
        """Test detecting line within a diff hunk."""
        diff = """@@ -10,5 +15,7 @@
 unchanged line
+added line
 more unchanged"""

        result = _is_line_in_diff_region(diff, 16)

        assert result is True

    def test_line_within_tolerance(self):
        """Test line within tolerance range."""
        diff = "@@ -1,3 +1,5 @@"

        # Line 5 is within tolerance of hunk ending at ~5
        result = _is_line_in_diff_region(diff, 5, tolerance=5)

        assert result is True

    def test_line_outside_all_hunks(self):
        """Test line completely outside any diff hunk."""
        diff = "@@ -1,3 +1,3 @@"

        result = _is_line_in_diff_region(diff, 100)

        assert result is False

    def test_multiple_hunks(self):
        """Test with multiple diff hunks."""
        diff = """@@ -1,3 +1,4 @@
+added
@@ -50,3 +51,5 @@
+another added"""

        # Line 52 should be in second hunk
        result = _is_line_in_diff_region(diff, 52)

        assert result is True


class TestFindResolvedIssues:
    """Tests for find_resolved_issues function."""

    def test_finds_resolved_in_changed_files(self):
        """Test finding resolved issues in changed files."""
        previous_comments = [
            {
                "file": "src/foo.py",
                "line": 42,
                "issue_type": "naming",
                "pattern_hash": "abc123",
                "comment_id": 111,
                "original_text": "Use snake_case",
            }
        ]

        resolved = find_resolved_issues(
            previous_comments=previous_comments,
            changed_files=["src/foo.py", "src/bar.py"],
        )

        assert len(resolved) == 1
        assert resolved[0].fingerprint.file_path == "src/foo.py"
        assert resolved[0].resolution_type == "fixed"

    def test_ignores_unchanged_files(self):
        """Test that issues in unchanged files are not marked resolved."""
        previous_comments = [
            {
                "file": "src/untouched.py",
                "line": 10,
                "issue_type": "style",
                "pattern_hash": "xyz",
            }
        ]

        resolved = find_resolved_issues(
            previous_comments=previous_comments,
            changed_files=["src/other.py"],
        )

        assert len(resolved) == 0

    def test_handles_diff_region_check(self):
        """Test more precise matching with diff content."""
        previous_comments = [
            {
                "file": "src/foo.py",
                "line": 42,
                "issue_type": "naming",
                "pattern_hash": "abc",
            }
        ]

        # Diff that changes lines 40-45
        current_diffs = {"src/foo.py": "@@ -38,10 +38,12 @@"}

        resolved = find_resolved_issues(
            previous_comments=previous_comments,
            changed_files=["src/foo.py"],
            current_diffs=current_diffs,
        )

        assert len(resolved) == 1

    def test_skips_untouched_regions(self):
        """Test that issues in untouched regions are not marked resolved."""
        previous_comments = [
            {
                "file": "src/foo.py",
                "line": 200,  # Far from the diff
                "issue_type": "naming",
                "pattern_hash": "abc",
            }
        ]

        # Diff only changes lines 1-10
        current_diffs = {"src/foo.py": "@@ -1,5 +1,10 @@"}

        resolved = find_resolved_issues(
            previous_comments=previous_comments,
            changed_files=["src/foo.py"],
            current_diffs=current_diffs,
        )

        assert len(resolved) == 0


class TestBuildCommentsForStorage:
    """Tests for build_comments_for_storage function."""

    def test_builds_fingerprints_from_comments(self):
        """Test converting review comments to fingerprints."""
        comments = [
            {
                "file_path": "src/app.py",
                "line_number": 42,
                "comment_body": "Variable `foo` should use snake_case",
                "comment_id": 12345,
            },
            {
                "file_path": "src/utils.py",
                "line_number": 100,
                "body": "Add exception handling",  # Alternative key
            },
        ]

        result = build_comments_for_storage(comments)

        assert len(result) == 2
        assert result[0]["file"] == "src/app.py"
        assert result[0]["line"] == 42
        assert result[0]["issue_type"] == "naming"
        assert result[1]["file"] == "src/utils.py"
        assert result[1]["issue_type"] == "error_handling"

    def test_handles_malformed_comments(self):
        """Test graceful handling of malformed comment data."""
        comments = [
            {"file_path": "good.py", "line_number": 1, "comment_body": "Good comment"},
            {},  # Empty dict
            {"not_a_valid_field": "value"},  # Missing required fields
        ]

        result = build_comments_for_storage(comments)

        # Should at least get one valid fingerprint
        assert len(result) >= 1
        assert result[0]["file"] == "good.py"
