#!/usr/bin/env python3
"""Script to perform one-time full codebase indexing for a repository."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from github import Auth, Github

from src.services.codebase_index_service import codebase_index_service
from src.services.github_auth import get_github_app_auth

logger = logging.getLogger(__name__)


async def backfill(repo_name: str, ref: str, delay: float) -> None:
    """Run codebase backfill for the specified repository and git ref."""
    logger.info(
        "Starting codebase index backfill for %s at ref '%s'...",
        repo_name,
        ref,
    )

    if not codebase_index_service.is_available():
        logger.error(
            "Codebase index service is not available (check Pinecone configuration)."
        )
        sys.exit(1)

    try:
        github_auth = get_github_app_auth()
        token = await github_auth.get_installation_access_token()
        auth = Auth.Token(token)
        github_client = Github(auth=auth)

        repo = github_client.get_repo(repo_name)

        result = await codebase_index_service.index_full_repo(
            repo, ref=ref, delay_seconds=delay
        )
        logger.info(
            "Backfill completed successfully for %s:\n"
            "  Files Indexed: %d\n"
            "  Files Skipped: %d",
            repo_name,
            result.files_indexed,
            len(result.files_skipped),
        )
        for skipped in result.files_skipped[:10]:
            logger.info("  Skipped %s: %s", skipped["file"], skipped["reason"])
        if len(result.files_skipped) > 10:
            logger.info(
                "  ... and %d more files skipped.",
                len(result.files_skipped) - 10,
            )

    except Exception as e:
        logger.error("Backfill failed: %s", e)
        sys.exit(1)


def main() -> None:
    """Parse arguments and start backfill."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )

    parser = argparse.ArgumentParser(
        description="Backfill Pinecone codebase index for a repository."
    )
    parser.add_argument("repo", help="Repository full name (e.g. owner/repo)")
    parser.add_argument(
        "--ref", default="main", help="Git ref to index (default: main)"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Delay in seconds between processing individual files to avoid rate limits (default: 0.0)",
    )
    args = parser.parse_args()

    asyncio.run(backfill(args.repo, args.ref, args.delay))


if __name__ == "__main__":
    main()
