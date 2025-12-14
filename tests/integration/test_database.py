"""Integration tests for database operations."""

import os
from datetime import datetime, timezone

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from src.models.conversation import Base, ConversationThread

# Load environment variables from .env.local
load_dotenv(".env.local")


@pytest.fixture(scope="module")
def test_db_url() -> str:
    """
    Get test database URL from environment.

    Priority:
    1. TEST_DATABASE_URL - explicit test database (PostgreSQL or SQLite)
    2. Default: SQLite in-memory database (fast, free, no setup required)

    For CI/CD or integration testing against real PostgreSQL:
    - Set TEST_DATABASE_URL to PostgreSQL connection string
    """
    # Check for explicit test database URL
    test_url = os.getenv("TEST_DATABASE_URL")
    if test_url:
        return test_url

    # Default: SQLite in-memory database (free, fast, no external dependencies)
    return "sqlite:///:memory:"


@pytest.fixture(scope="module")
def test_engine(test_db_url: str):
    """Create a test database engine."""
    engine = create_engine(test_db_url, echo=False)
    return engine


@pytest.fixture(scope="module")
def test_session_factory(test_engine):
    """Create a session factory for tests."""
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="module", autouse=True)
def setup_test_database(test_engine):
    """Setup test database tables before tests and tear down after."""
    # Create all tables
    Base.metadata.create_all(bind=test_engine)
    yield
    # Drop all tables after tests
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session(test_session_factory, test_engine, test_db_url: str) -> Session:
    """Provide a clean database session for each test."""
    session = test_session_factory()
    yield session
    session.close()

    # Clean up all data after each test to avoid unique constraint violations
    # Use database-specific cleanup methods
    with test_engine.begin() as conn:
        if "sqlite" in test_db_url:
            # SQLite: DELETE is simpler and works for in-memory databases
            conn.execute(text("DELETE FROM conversation_threads"))
        else:
            # PostgreSQL: TRUNCATE is faster and resets sequences
            conn.execute(
                text("TRUNCATE TABLE conversation_threads RESTART IDENTITY CASCADE")
            )


@pytest.fixture
def sample_thread_data() -> dict:
    """Sample conversation thread data for testing."""
    return {
        "repo_full_name": "test-org/test-repo",
        "pr_number": 123,
        "comment_id": 456789,
        "thread_type": "inline_comment",
        "status": "active",
        "thread_messages": [
            {
                "role": "bot",
                "content": "This variable should use snake_case per PEP 8",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "comment_id": 456789,
            }
        ],
        "original_file_path": "src/main.py",
        "original_line_number": 42,
        "original_suggestion": "Rename `userName` to `user_name`",
    }


class TestDatabaseConnection:
    """Test database connection and basic operations."""

    def test_database_connection(self, test_engine):
        """Test that database connection works."""
        with test_engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    def test_tables_created(self, test_engine):
        """Test that all tables are created."""
        inspector = inspect(test_engine)
        tables = inspector.get_table_names()
        assert "conversation_threads" in tables


class TestConversationThreadCRUD:
    """Test CRUD operations for ConversationThread model."""

    def test_create_conversation_thread(
        self, db_session: Session, sample_thread_data: dict
    ):
        """Test creating a new conversation thread."""
        thread = ConversationThread(**sample_thread_data)
        db_session.add(thread)
        db_session.commit()
        db_session.refresh(thread)

        assert thread.id is not None
        assert thread.repo_full_name == sample_thread_data["repo_full_name"]
        assert thread.pr_number == sample_thread_data["pr_number"]
        assert thread.comment_id == sample_thread_data["comment_id"]
        assert thread.thread_type == sample_thread_data["thread_type"]
        assert thread.status == "active"
        assert len(thread.thread_messages) == 1
        assert thread.created_at is not None
        assert thread.updated_at is not None

    def test_read_conversation_thread(
        self, db_session: Session, sample_thread_data: dict
    ):
        """Test reading a conversation thread by ID."""
        # Create thread
        thread = ConversationThread(**sample_thread_data)
        db_session.add(thread)
        db_session.commit()
        thread_id = thread.id

        # Read thread
        db_session.expire_all()
        retrieved_thread = (
            db_session.query(ConversationThread)
            .filter(ConversationThread.id == thread_id)
            .first()
        )

        assert retrieved_thread is not None
        assert retrieved_thread.id == thread_id
        assert retrieved_thread.repo_full_name == sample_thread_data["repo_full_name"]

    def test_read_thread_by_comment_id(
        self, db_session: Session, sample_thread_data: dict
    ):
        """Test reading a conversation thread by comment_id (unique index)."""
        # Create thread
        thread = ConversationThread(**sample_thread_data)
        db_session.add(thread)
        db_session.commit()

        # Read by comment_id
        db_session.expire_all()
        retrieved_thread = (
            db_session.query(ConversationThread)
            .filter(ConversationThread.comment_id == sample_thread_data["comment_id"])
            .first()
        )

        assert retrieved_thread is not None
        assert retrieved_thread.comment_id == sample_thread_data["comment_id"]

    def test_update_conversation_thread(
        self, db_session: Session, sample_thread_data: dict
    ):
        """Test updating a conversation thread."""
        # Create thread
        thread = ConversationThread(**sample_thread_data)
        db_session.add(thread)
        db_session.commit()
        thread_id = thread.id

        # Update status
        db_session.expire_all()
        thread_to_update = (
            db_session.query(ConversationThread)
            .filter(ConversationThread.id == thread_id)
            .first()
        )
        thread_to_update.status = "resolved"
        db_session.commit()

        # Verify update
        db_session.expire_all()
        updated_thread = (
            db_session.query(ConversationThread)
            .filter(ConversationThread.id == thread_id)
            .first()
        )
        assert updated_thread.status == "resolved"

    def test_delete_conversation_thread(
        self, db_session: Session, sample_thread_data: dict
    ):
        """Test deleting a conversation thread."""
        # Create thread
        thread = ConversationThread(**sample_thread_data)
        db_session.add(thread)
        db_session.commit()
        thread_id = thread.id

        # Delete thread
        db_session.expire_all()
        thread_to_delete = (
            db_session.query(ConversationThread)
            .filter(ConversationThread.id == thread_id)
            .first()
        )
        db_session.delete(thread_to_delete)
        db_session.commit()

        # Verify deletion
        db_session.expire_all()
        deleted_thread = (
            db_session.query(ConversationThread)
            .filter(ConversationThread.id == thread_id)
            .first()
        )
        assert deleted_thread is None


class TestConversationThreadMethods:
    """Test ConversationThread model methods."""

    def test_add_message(self, db_session: Session, sample_thread_data: dict):
        """Test adding a message to a conversation thread."""
        thread = ConversationThread(**sample_thread_data)
        db_session.add(thread)
        db_session.commit()

        initial_message_count = len(thread.thread_messages)
        initial_updated_at = thread.updated_at
        if initial_updated_at.tzinfo is None:
            initial_updated_at = initial_updated_at.replace(tzinfo=timezone.utc)

        # Add a new message
        thread.add_message(
            role="developer", content="Why should I use snake_case?", comment_id=456790
        )
        db_session.commit()

        assert len(thread.thread_messages) == initial_message_count + 1
        assert thread.thread_messages[-1]["role"] == "developer"
        assert thread.thread_messages[-1]["content"] == "Why should I use snake_case?"
        assert thread.thread_messages[-1]["comment_id"] == 456790

        current_updated_at = thread.updated_at
        if current_updated_at.tzinfo is None:
            current_updated_at = current_updated_at.replace(tzinfo=timezone.utc)
        assert current_updated_at > initial_updated_at

    def test_get_context_for_llm(self, db_session: Session, sample_thread_data: dict):
        """Test formatting thread messages for LLM context."""
        thread = ConversationThread(**sample_thread_data)
        thread.add_message(role="developer", content="Why?")
        thread.add_message(
            role="bot", content="Because PEP 8 is the Python style guide"
        )

        llm_context = thread.get_context_for_llm()

        assert len(llm_context) == 3
        assert llm_context[0]["role"] == "assistant"  # bot -> assistant
        assert llm_context[1]["role"] == "user"  # developer -> user
        assert llm_context[2]["role"] == "assistant"  # bot -> assistant

    def test_mark_resolved(self, db_session: Session, sample_thread_data: dict):
        """Test marking a thread as resolved."""
        thread = ConversationThread(**sample_thread_data)
        db_session.add(thread)
        db_session.commit()

        initial_updated_at = thread.updated_at
        if initial_updated_at.tzinfo is None:
            initial_updated_at = initial_updated_at.replace(tzinfo=timezone.utc)
        thread.mark_resolved()

        assert thread.status == "resolved"

        current_updated_at = thread.updated_at
        if current_updated_at.tzinfo is None:
            current_updated_at = current_updated_at.replace(tzinfo=timezone.utc)
        assert current_updated_at > initial_updated_at

    def test_mark_abandoned(self, db_session: Session, sample_thread_data: dict):
        """Test marking a thread as abandoned."""
        thread = ConversationThread(**sample_thread_data)
        db_session.add(thread)
        db_session.commit()

        initial_updated_at = thread.updated_at
        if initial_updated_at.tzinfo is None:
            initial_updated_at = initial_updated_at.replace(tzinfo=timezone.utc)
        thread.mark_abandoned()

        assert thread.status == "abandoned"

        current_updated_at = thread.updated_at
        if current_updated_at.tzinfo is None:
            current_updated_at = current_updated_at.replace(tzinfo=timezone.utc)
        assert current_updated_at > initial_updated_at


class TestConversationThreadQueries:
    """Test complex queries on ConversationThread."""

    def test_query_threads_by_repo(self, db_session: Session, sample_thread_data: dict):
        """Test querying threads by repository."""
        # Create threads for different repos
        thread1 = ConversationThread(**sample_thread_data)
        thread2_data = sample_thread_data.copy()
        thread2_data["repo_full_name"] = "other-org/other-repo"
        thread2_data["comment_id"] = 999999
        thread2 = ConversationThread(**thread2_data)

        db_session.add_all([thread1, thread2])
        db_session.commit()

        # Query by repo
        threads = (
            db_session.query(ConversationThread)
            .filter(
                ConversationThread.repo_full_name
                == sample_thread_data["repo_full_name"]
            )
            .all()
        )

        assert len(threads) == 1
        assert threads[0].repo_full_name == sample_thread_data["repo_full_name"]

    def test_query_threads_by_pr(self, db_session: Session, sample_thread_data: dict):
        """Test querying threads by PR number."""
        # Create threads for different PRs
        thread1 = ConversationThread(**sample_thread_data)
        thread2_data = sample_thread_data.copy()
        thread2_data["pr_number"] = 999
        thread2_data["comment_id"] = 999999
        thread2 = ConversationThread(**thread2_data)

        db_session.add_all([thread1, thread2])
        db_session.commit()

        # Query by PR
        threads = (
            db_session.query(ConversationThread)
            .filter(
                ConversationThread.repo_full_name
                == sample_thread_data["repo_full_name"]
            )
            .filter(ConversationThread.pr_number == sample_thread_data["pr_number"])
            .all()
        )

        assert len(threads) == 1
        assert threads[0].pr_number == sample_thread_data["pr_number"]

    def test_query_active_threads(self, db_session: Session, sample_thread_data: dict):
        """Test querying only active threads."""
        # Create threads with different statuses
        thread1 = ConversationThread(**sample_thread_data)
        thread2_data = sample_thread_data.copy()
        thread2_data["comment_id"] = 999999
        thread2_data["status"] = "resolved"
        thread2 = ConversationThread(**thread2_data)

        db_session.add_all([thread1, thread2])
        db_session.commit()

        # Query active threads
        active_threads = (
            db_session.query(ConversationThread)
            .filter(ConversationThread.status == "active")
            .all()
        )

        assert len(active_threads) == 1
        assert active_threads[0].status == "active"
