"""Setup Pinecone index for RAG knowledge base."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env.local
env_path = Path(__file__).parent.parent / ".env.local"
load_dotenv(env_path)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pinecone import Pinecone, ServerlessSpec  # noqa: E402


def setup_pinecone_index():
    """Create Pinecone serverless index if it doesn't exist."""
    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        print(" Error: PINECONE_API_KEY not found in environment")
        print("   Please set it in your .env.local file")
        return False

    index_name = "code-style-guides"

    print("🔧 Initializing Pinecone client...")
    pc = Pinecone(api_key=api_key)

    # Check if index exists
    existing_indexes = pc.list_indexes()
    index_names = [idx.name for idx in existing_indexes.indexes]

    if index_name in index_names:
        print(f" Index '{index_name}' already exists")

        # Get index info
        index_info = pc.describe_index(index_name)
        print(f"   Dimension: {index_info.dimension}")
        print(f"   Metric: {index_info.metric}")
        print(f"   Host: {index_info.host}")
        return True

    print(f" Creating serverless index '{index_name}'...")
    print("   This may take 1-2 minutes...")

    pc.create_index(
        name=index_name,
        dimension=1536,  # text-embedding-3-small dimension
        metric="cosine",
        spec=ServerlessSpec(
            cloud="aws",
            region="us-east-1",  # Closest to Railway US deployments
        ),
    )

    print(f" Index '{index_name}' created successfully!")
    print("   Dimension: 1536 (text-embedding-3-small)")
    print("   Metric: cosine")
    print("   Cloud: AWS us-east-1")

    return True


if __name__ == "__main__":
    print("=" * 60)
    print("Pinecone Index Setup for RAG Knowledge Base")
    print("=" * 60)
    print()

    success = setup_pinecone_index()

    print()
    if success:
        print(" Setup complete! Ready to index documents.")
        print()
        print("Next steps:")
        print("1. Create documents.yaml configuration")
        print("2. Run: python scripts/index_documents.py")
    else:
        print(" Setup failed. Please fix the errors above.")
        sys.exit(1)
