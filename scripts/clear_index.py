"""Clear all vectors from Pinecone index."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pinecone import Pinecone

# Load environment variables
env_path = Path(__file__).parent.parent / ".env.local"
load_dotenv(env_path)

api_key = os.getenv("PINECONE_API_KEY")
index_name = os.getenv("PINECONE_INDEX_NAME", "code-style-guides")

if not api_key:
    print("Error: PINECONE_API_KEY not found")
    exit(1)

pc = Pinecone(api_key=api_key)
index = pc.Index(index_name)

# Get current stats
stats = index.describe_index_stats()
print("Current index stats:")
print(f"  Total vectors: {stats.total_vector_count}")
print(f"  Namespaces: {list(stats.namespaces.keys())}")

# Delete all vectors from all namespaces
print("\nDeleting all vectors...")
for namespace in stats.namespaces:
    index.delete(delete_all=True, namespace=namespace)
    print(f"  Deleted namespace: {namespace}")

print("\nAll vectors deleted. Ready to re-index.")
