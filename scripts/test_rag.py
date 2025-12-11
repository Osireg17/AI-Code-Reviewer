"""Test RAG service with sample queries."""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent / ".env.local"
load_dotenv(env_path)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.settings import settings
from src.services.rag_service import rag_service


async def test_rag_queries():
    """Test RAG service with various queries."""
    if not rag_service.is_available():
        print("RAG service is not available")
        return

    print("=" * 70)
    print("Testing RAG Service")
    print("=" * 70)
    print(f"Min similarity threshold: {settings.rag_min_similarity}")
    print()

    # Test queries for different languages
    test_cases = [
        {
            "query": "variable naming conventions",
            "language": "python",
        },
        {
            "query": "error handling best practices",
            "language": "javascript",
        },
        {
            "query": "security vulnerabilities",
            "language": "cross-language",
        },
    ]

    for i, test_case in enumerate(test_cases, 1):
        print(f"[Test {i}/{len(test_cases)}]")
        print(f"Query: '{test_case['query']}' | Language: {test_case['language']}")

        try:
            results = await rag_service.search_style_guides(
                query=test_case["query"],
                language=test_case["language"],
                top_k=3,
            )

            if results:
                print(f"Found {len(results)} results:\n")
                for j, result in enumerate(results, 1):
                    print(f"  [{j}] {result['metadata'].get('source')} ({result['metadata'].get('language')})")
                    print(f"      Similarity: {result['similarity']:.2%}")
                    print(f"      Preview: {result['content'][:120]}...\n")
            else:
                print("No results found\n")

        except Exception as e:
            print(f"Error: {e}\n")

        print("-" * 70)
        print()

    print("Testing complete!")


if __name__ == "__main__":
    asyncio.run(test_rag_queries())