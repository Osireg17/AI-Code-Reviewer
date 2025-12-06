"""File filtering utilities for determining which files to review."""

import re
from pathlib import Path
from re import Pattern

# Patterns for files/directories that should be excluded from review
EXCLUDED_PATTERNS: list[Pattern[str]] = [
    # Lock files
    re.compile(r"package-lock\.json$"),
    re.compile(r"yarn\.lock$"),
    re.compile(r"Pipfile\.lock$"),
    re.compile(r"poetry\.lock$"),
    re.compile(r"Gemfile\.lock$"),
    re.compile(r"pnpm-lock\.yaml$"),
    re.compile(r"composer\.lock$"),
    # Build/dist directories
    re.compile(r"^dist/"),
    re.compile(r"^build/"),
    re.compile(r"^out/"),
    re.compile(r"^target/"),
    re.compile(r"^\.next/"),
    re.compile(r"^__pycache__/"),
    # Dependencies
    re.compile(r"^node_modules/"),
    re.compile(r"^vendor/"),
    re.compile(r"^venv/"),
    re.compile(r"^\.venv/"),
    # Generated code
    re.compile(r"\.generated\.[^/]+$"),
    re.compile(r"\.g\.dart$"),
    re.compile(r"\.pb\.go$"),
    re.compile(r"_pb2\.py$"),
    # Minified files
    re.compile(r"\.min\.js$"),
    re.compile(r"\.min\.css$"),
    # Binary/media files
    re.compile(r"\.(png|jpg|jpeg|gif|svg|ico|webp)$"),
    re.compile(r"\.(pdf|zip|tar|gz|rar|7z)$"),
    re.compile(r"\.(mp4|mp3|avi|mov|wav)$"),
    re.compile(r"\.(ttf|woff|woff2|eot|otf)$"),
    # Database files
    re.compile(r"\.db$"),
    re.compile(r"\.sqlite$"),
    re.compile(r"\.sqlite3$"),
    # IDE files
    re.compile(r"^\.vscode/"),
    re.compile(r"^\.idea/"),
    re.compile(r"\.swp$"),
    re.compile(r"\.swo$"),
    # Git
    re.compile(r"^\.git/"),
]

# Common programming language file extensions
CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".go",
    ".java",
    ".kt",
    ".kts",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".rs",
    ".rb",
    ".php",
    ".swift",
    ".m",
    ".scala",
    ".sh",
    ".bash",
    ".zsh",
    ".dart",
    ".vue",
    ".svelte",
}

# Configuration file extensions
CONFIG_EXTENSIONS = {
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".conf",
    ".xml",
    ".env",
}


def should_review_file(file_path: str) -> bool:
    """Determine if a file should be included in code review.

    Args:
        file_path: Path to the file (relative or absolute)

    Returns:
        True if the file should be reviewed, False if it should be excluded
    """
    # Normalize path for consistent matching
    normalized_path = str(Path(file_path))

    # Check against exclusion patterns - return True if no patterns match
    return all(not pattern.search(normalized_path) for pattern in EXCLUDED_PATTERNS)


def is_code_file(file_path: str) -> bool:
    """Check if a file is a code file based on extension.

    Args:
        file_path: Path to the file

    Returns:
        True if the file has a code extension
    """
    extension = Path(file_path).suffix.lower()
    return extension in CODE_EXTENSIONS


def is_config_file(file_path: str) -> bool:
    """Check if a file is a configuration file based on extension.

    Args:
        file_path: Path to the file

    Returns:
        True if the file has a config extension
    """
    extension = Path(file_path).suffix.lower()
    return extension in CONFIG_EXTENSIONS


def prioritize_files(file_paths: list[str], max_files: int = 10) -> list[str]:
    """Prioritize and limit files for review.

    Filters out excluded files and prioritizes in this order:
    1. Code files (.py, .js, .ts, etc.)
    2. Configuration files (.json, .yaml, etc.)
    3. Other reviewable files

    Args:
        file_paths: List of file paths to prioritize
        max_files: Maximum number of files to return

    Returns:
        Prioritized and limited list of file paths
    """
    # Filter to only reviewable files
    reviewable = [f for f in file_paths if should_review_file(f)]

    # Separate into categories
    code_files = [f for f in reviewable if is_code_file(f)]
    config_files = [f for f in reviewable if is_config_file(f) and not is_code_file(f)]
    other_files = [
        f for f in reviewable if not is_code_file(f) and not is_config_file(f)
    ]

    # Combine in priority order
    prioritized = code_files + config_files + other_files

    # Limit to max_files
    return prioritized[:max_files]
