"""Index coding convention documents into Pinecone vector database."""

import argparse
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pinecone import Pinecone

# Load environment variables from .env.local
env_path = Path(__file__).parent.parent / ".env.local"
load_dotenv(env_path)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def load_documents_config(config_path: Path) -> list[dict]:
    """Load documents configuration from YAML file."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_document(file_path: Path) -> list:
    """Load a document using appropriate loader based on file type."""
    if file_path.suffix.lower() == ".pdf":
        loader = PyPDFLoader(str(file_path))
    elif file_path.suffix.lower() in [".md", ".txt"]:
        loader = TextLoader(str(file_path))
    else:
        raise ValueError(f"Unsupported file type: {file_path.suffix}")

    return loader.load()


def chunk_documents(documents: list, chunk_size: int = 1000, chunk_overlap: int = 200):
    """Split documents into chunks for embedding."""
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return text_splitter.split_documents(documents)


def index_documents(specific_file: str = None):
    """Index all documents from configuration into Pinecone.

    Args:
        specific_file: Optional relative file path (e.g., 'Python/PEP8.pdf') to index only that file
    """
    # Validate environment variables
    api_key = os.getenv("PINECONE_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    index_name = os.getenv("PINECONE_INDEX_NAME", "code-style-guides")

    if not api_key:
        print(" Error: PINECONE_API_KEY not found in environment")
        return False

    if not openai_key:
        print(" Error: OPENAI_API_KEY not found in environment")
        return False

    # Load configuration
    project_root = Path(__file__).parent.parent
    config_path = project_root / "Coding Conventions" / "documents.yaml"
    docs_base_path = project_root / "Coding Conventions"

    if not config_path.exists():
        print(f" Error: Configuration file not found: {config_path}")
        return False

    print("=" * 70)
    if specific_file:
        print(f"Document Indexing: {specific_file}")
    else:
        print("Document Indexing for RAG Knowledge Base")
    print("=" * 70)
    print()

    # Initialize Pinecone
    print("Initializing Pinecone client...")
    pc = Pinecone(api_key=api_key)

    # Verify index exists
    existing_indexes = [idx.name for idx in pc.list_indexes().indexes]
    if index_name not in existing_indexes:
        print(f" Error: Index '{index_name}' does not exist")
        print(f"   Available indexes: {existing_indexes}")
        print("   Run 'python scripts/setup_pinecone.py' first")
        return False

    index = pc.Index(index_name)
    print(f" Connected to index: {index_name}")
    print()

    # Initialize embeddings
    print("Initializing OpenAI embeddings...")
    embeddings = OpenAIEmbeddings(
        model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        openai_api_key=openai_key,
    )
    print(" Embeddings initialized")
    print()

    # Load document configuration
    print("Loading document configuration...")
    doc_configs = load_documents_config(config_path)

    # Filter to specific file if requested
    if specific_file:
        doc_configs = [dc for dc in doc_configs if dc["file_path"] == specific_file]
        if not doc_configs:
            print(f" Error: File '{specific_file}' not found in documents.yaml")
            print("   Make sure the path matches exactly (e.g., 'Python/PEP8.pdf')")
            return False
        print(f" Found configuration for: {specific_file}")
    else:
        print(f" Found {len(doc_configs)} documents to index")
    print()

    # Process each document
    total_chunks = 0
    processed_docs = 0
    failed_docs = []

    for i, doc_config in enumerate(doc_configs, 1):
        file_path = docs_base_path / doc_config["file_path"]
        namespace = doc_config["namespace"]
        language = doc_config["language"]
        source = doc_config["source"]

        print(f"[{i}/{len(doc_configs)}] Processing: {file_path.name}")
        print(f"   Language: {language} | Namespace: {namespace} | Source: {source}")

        if not file_path.exists():
            print("   Warning: File not found, skipping")
            failed_docs.append((str(file_path), "File not found"))
            print()
            continue

        try:
            # Load document
            print("   Loading document...")
            documents = load_document(file_path)
            print(f"   Loaded {len(documents)} pages")

            # Add metadata to all pages (filter out null values)
            for doc in documents:
                metadata = {
                    "language": language,
                    "namespace": namespace,
                    "source": source,
                    "document_type": doc_config.get("document_type", "unknown"),
                    "file_name": file_path.name,
                }
                # Only add URL if it's not null
                if doc_config.get("url"):
                    metadata["url"] = doc_config["url"]

                doc.metadata.update(metadata)

            # Chunk documents
            print("   Chunking document...")
            chunks = chunk_documents(documents)
            print(f"   Created {len(chunks)} chunks")

            # Upload to Pinecone with namespace
            print(f"   Uploading to Pinecone (namespace: {namespace})...")
            vector_store = PineconeVectorStore(
                index=index,
                embedding=embeddings,
                namespace=namespace,
            )

            # Add documents in batches to avoid rate limits
            batch_size = 50
            for j in range(0, len(chunks), batch_size):
                batch = chunks[j : j + batch_size]
                vector_store.add_documents(batch)
                print(
                    f"   Uploaded batch {j // batch_size + 1}/{(len(chunks) + batch_size - 1) // batch_size}"
                )

            total_chunks += len(chunks)
            processed_docs += 1
            print(f"   Successfully indexed {len(chunks)} chunks")

        except Exception as e:
            print(f"   Error processing document: {e}")
            failed_docs.append((str(file_path), str(e)))

        print()

    # Summary
    print("=" * 70)
    print("Indexing Summary")
    print("=" * 70)
    print(f" Successfully processed: {processed_docs}/{len(doc_configs)} documents")
    print(f" Total chunks indexed: {total_chunks}")
    print(f" Index name: {index_name}")
    print()

    if failed_docs:
        print(" Failed documents:")
        for file_path, error in failed_docs:
            print(f"   - {file_path}: {error}")
        print()

    # Get index stats
    print("Checking index statistics...")
    stats = index.describe_index_stats()
    print(f"   Total vectors: {stats.total_vector_count}")
    print(f"   Namespaces: {list(stats.namespaces.keys())}")
    for ns, ns_stats in stats.namespaces.items():
        print(f"      - {ns}: {ns_stats.vector_count} vectors")
    print()

    print(" Indexing complete!")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Index coding convention documents into Pinecone",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Index all documents
  python scripts/index_documents.py

  # Index a specific file
  python scripts/index_documents.py --file "Python/Fluent_Python.pdf"
  python scripts/index_documents.py -f "TypeScript/Programming TypeScript - Boris Cherny - O'Reilly (2019).pdf"
        """,
    )
    parser.add_argument(
        "-f",
        "--file",
        type=str,
        help="Index only this specific file (relative path from Coding Conventions/, e.g., 'Python/PEP8.pdf')",
    )

    args = parser.parse_args()
    success = index_documents(specific_file=args.file)
    sys.exit(0 if success else 1)
