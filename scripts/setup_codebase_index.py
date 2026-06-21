"""Setup Pinecone index for semantic codebase search."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env.local"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent))

from pinecone import Pinecone, ServerlessSpec  # noqa: E402


def setup_codebase_index() -> bool:
    """Create Pinecone serverless index for codebase semantic search if it doesn't exist."""
    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        print("Error: PINECONE_API_KEY not found in environment")
        print("  Please set it in your .env.local file")
        return False

    index_name = os.getenv("PINECONE_CODEBASE_INDEX_NAME", "codebase-index")

    print("Initializing Pinecone client...")
    pc = Pinecone(api_key=api_key)

    existing_indexes = pc.list_indexes()
    index_names = [idx.name for idx in existing_indexes.indexes]

    if index_name in index_names:
        print(f"Index '{index_name}' already exists")
        index_info = pc.describe_index(index_name)
        print(f"  Dimension: {index_info.dimension}")
        print(f"  Metric:    {index_info.metric}")
        print(f"  Host:      {index_info.host}")
        return True

    print(f"Creating serverless index '{index_name}'...")
    print("  This may take 1-2 minutes...")

    pc.create_index(
        name=index_name,
        dimension=1536,  # text-embedding-3-small
        metric="cosine",
        spec=ServerlessSpec(
            cloud="aws",
            region="us-east-1",
        ),
    )

    print(f"Index '{index_name}' created successfully!")
    print("  Dimension: 1536 (text-embedding-3-small)")
    print("  Metric:    cosine")
    print("  Cloud:     AWS us-east-1")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("Pinecone Index Setup — Semantic Codebase Search")
    print("=" * 60)
    print()

    success = setup_codebase_index()

    print()
    if success:
        print("Setup complete. The index will populate as PRs are reviewed.")
        print()
        print("Next steps:")
        print(
            "1. Set PINECONE_CODEBASE_INDEX_NAME=codebase-index in .env.local (if not set)"
        )
        print(
            "2. Deploy and open a PR — indexing runs automatically before each review"
        )
    else:
        print("Setup failed. Please fix the errors above.")
        sys.exit(1)
