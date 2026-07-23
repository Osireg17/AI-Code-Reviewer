"""Unit tests for RabbitMQ service."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.rabbitmq_service import RabbitMQService


class MockProcessCtx:
    """Mock async context manager for message.process()."""

    def __init__(self, on_exit: MagicMock | None = None) -> None:
        self.on_exit = on_exit

    async def __aenter__(self) -> "MockProcessCtx":
        return self

    async def __aexit__(self, exc_type: type, exc: Exception, tb: Any) -> None:
        if self.on_exit:
            self.on_exit(exc_type, exc, tb)


class MockMessage:
    """Mock aio_pika Message."""

    def __init__(
        self, body_dict: dict, on_process_exit: MagicMock | None = None
    ) -> None:
        self.body = json.dumps(body_dict).encode("utf-8")
        self.process_called_with = None
        self.on_process_exit = on_process_exit

    def process(self, requeue: bool = True) -> MockProcessCtx:
        self.process_called_with = requeue
        return MockProcessCtx(self.on_process_exit)


class MockQueueIter:
    """Mock async iterator for aio_pika queue."""

    def __init__(self, message: MockMessage) -> None:
        self.message = message
        self._sent = False

    async def __aenter__(self) -> "MockQueueIter":
        return self

    async def __aexit__(self, exc_type: type, exc: Exception, tb: Any) -> None:
        pass

    def __aiter__(self) -> "MockQueueIter":
        return self

    async def __anext__(self) -> MockMessage:
        if not self._sent:
            self._sent = True
            return self.message
        raise StopAsyncIteration


@patch("src.services.rabbitmq_service.settings")
def test_is_available_false_when_no_url(mock_settings) -> None:
    """Test is_available returns False when rabbitmq_url is not set."""
    mock_settings.rabbitmq_url = ""
    service = RabbitMQService()
    assert not service.is_available()


@patch("src.services.rabbitmq_service.settings")
def test_is_available_true_when_url(mock_settings) -> None:
    """Test is_available returns True when rabbitmq_url is set."""
    mock_settings.rabbitmq_url = (
        "amqp://guest:guest@localhost/"  # pragma: allowlist secret
    )
    service = RabbitMQService()
    assert service.is_available()


@pytest.mark.asyncio
@patch("src.services.rabbitmq_service.settings")
@patch("aio_pika.connect_robust")
async def test_publish_sends_correct_message(mock_connect, mock_settings) -> None:
    """Test that publish_reindex_job connects and sends correct message to RabbitMQ."""
    mock_settings.rabbitmq_url = (
        "amqp://guest:guest@localhost/"  # pragma: allowlist secret
    )
    mock_settings.reindex_queue_name = "codebase_reindex"

    mock_connection = AsyncMock()
    mock_channel = AsyncMock()
    mock_queue = AsyncMock()
    mock_exchange = AsyncMock()

    mock_connect.return_value = mock_connection
    mock_connection.channel.return_value = mock_channel
    mock_channel.declare_queue.return_value = mock_queue
    mock_channel.default_exchange = mock_exchange

    service = RabbitMQService()
    await service.publish_reindex_job("owner/repo", 42, "abc123")

    # fmt: off
    mock_connect.assert_called_once_with("amqp://guest:guest@localhost/")  # pragma: allowlist secret
    # fmt: on
    mock_channel.declare_queue.assert_called_once_with("codebase_reindex", durable=True)

    mock_exchange.publish.assert_called_once()
    published_message = mock_exchange.publish.call_args[0][0]

    assert json.loads(published_message.body.decode("utf-8")) == {
        "repo_full_name": "owner/repo",
        "pr_number": 42,
        "head_sha": "abc123",
    }


@pytest.mark.asyncio
@patch("src.services.rabbitmq_service.settings")
@patch("aio_pika.connect_robust")
async def test_consume_acks_on_success(mock_connect, mock_settings) -> None:
    """Test that consume_reindex_jobs processes messages and supports normal ack behaviour."""
    mock_settings.rabbitmq_url = (
        "amqp://guest:guest@localhost/"  # pragma: allowlist secret
    )
    mock_settings.reindex_queue_name = "codebase_reindex"

    mock_connection = AsyncMock()
    mock_channel = AsyncMock()
    mock_queue = (
        MagicMock()
    )  # Use MagicMock so synchronous calls don't return coroutines

    mock_connect.return_value = mock_connection
    mock_connection.channel.return_value = mock_channel
    mock_channel.declare_queue.return_value = mock_queue

    # Set up mock message and queue iterator
    mock_message = MockMessage({"test": "data"})
    mock_queue.iterator.return_value = MockQueueIter(mock_message)

    callback = AsyncMock()

    service = RabbitMQService()
    await service.consume_reindex_jobs(callback)

    callback.assert_called_once_with({"test": "data"})
    assert mock_message.process_called_with is True


@pytest.mark.asyncio
@patch("src.services.rabbitmq_service.settings")
@patch("aio_pika.connect_robust")
async def test_consume_nacks_on_failure(mock_connect, mock_settings) -> None:
    """Test that exceptions during callback propagate out of the process context to trigger nack."""
    mock_settings.rabbitmq_url = (
        "amqp://guest:guest@localhost/"  # pragma: allowlist secret
    )
    mock_settings.reindex_queue_name = "codebase_reindex"

    mock_connection = AsyncMock()
    mock_channel = AsyncMock()
    mock_queue = MagicMock()

    mock_connect.return_value = mock_connection
    mock_connection.channel.return_value = mock_channel
    mock_channel.declare_queue.return_value = mock_queue

    on_exit_spy = MagicMock()
    mock_message = MockMessage({"test": "data"}, on_process_exit=on_exit_spy)
    mock_queue.iterator.return_value = MockQueueIter(mock_message)

    callback = AsyncMock(side_effect=ValueError("Test callback failure"))

    service = RabbitMQService()
    with pytest.raises(ValueError, match="Test callback failure"):
        await service.consume_reindex_jobs(callback)

    callback.assert_called_once_with({"test": "data"})
    # Verify the context manager received the exception (so it can trigger nack/requeue)
    on_exit_spy.assert_called_once()
    exc_type = on_exit_spy.call_args[0][0]
    assert issubclass(exc_type, ValueError)
