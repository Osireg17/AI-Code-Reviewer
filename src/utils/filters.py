"""File filtering utilities for determining which files to review."""

# TODO: Import re and Path from pathlib

# TODO: Define EXCLUDED_PATTERNS list with regex patterns for:
#   - Lock files (package-lock.json, yarn.lock, Pipfile.lock, etc.)
#   - Build/dist directories (dist/, build/, out/, target/, .next/)
#   - Dependencies (node_modules/, vendor/, venv/, .venv/)
#   - Generated code (*.generated.*, *.g.dart, *.pb.go, *_pb2.py)
#   - Minified files (*.min.js, *.min.css)
#   - Binary/media files (png, jpg, gif, svg, pdf, zip, etc.)
#   - Database files (*.db, *.sqlite)
#   - IDE files (.vscode/, .idea/, *.swp)
#   - Git files (.git/)

# TODO: Define CODE_EXTENSIONS set with common programming language extensions:
#   - .py, .js, .ts, .jsx, .tsx, .go, .java, .cpp, .c, .h, .rs, .rb, .php, etc.

# TODO: Define CONFIG_EXTENSIONS set:
#   - .json, .yaml, .yml, .toml, .ini, .conf, .xml

# TODO: Create should_review_file(file_path: str) -> bool:
#   - Check if file matches any EXCLUDED_PATTERNS
#   - Return False if excluded, True otherwise

# TODO: Create is_code_file(file_path: str) -> bool:
#   - Check if file extension is in CODE_EXTENSIONS
#   - Return True if it is

# TODO: Create is_config_file(file_path: str) -> bool:
#   - Check if file extension is in CONFIG_EXTENSIONS
#   - Return True if it is

# TODO: Create prioritize_files(file_paths: list[str], max_files: int = 10) -> list[str]:
#   - Filter to only reviewable files using should_review_file()
#   - Separate into code_files, config_files, other_files
#   - Combine in priority order (code first, then config, then other)
#   - Limit to max_files
#   - Return prioritized list
