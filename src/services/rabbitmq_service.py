"""RabbitMQ service for publishing and consuming codebase reindexing jobs."""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aio_pika

from src.config.settings import settings

logger = logging.getLogger(__name__)


class RabbitMQService:
    """Service to handle RabbitMQ communication for CDC indexing."""

    def __init__(self) -> None:
        """Initialize RabbitMQ settings."""
        self.url = settings.rabbitmq_url
        self.queue_name = settings.reindex_queue_name

    def is_available(self) -> bool:
        """Check if RabbitMQ is configured and available."""
        return bool(self.url)

    async def publish_reindex_job(
        self, repo_full_name: str, pr_number: int, head_sha: str
    ) -> None:
        """Publish a codebase reindexing job to RabbitMQ.

        Args:
            repo_full_name: Full repository name (owner/repo)
            pr_number: Pull request number
            head_sha: Head commit SHA to reindex
        """
        if not self.is_available():
            raise RuntimeError("RabbitMQ service is not available")

        message_body = {
            "repo_full_name": repo_full_name,
            "pr_number": pr_number,
            "head_sha": head_sha,
        }

        logger.info("Connecting to RabbitMQ to publish reindex job...")
        connection = await aio_pika.connect_robust(self.url)
        async with connection:
            channel = await connection.channel()
            # Declare a durable queue
            await channel.declare_queue(self.queue_name, durable=True)

            message_json = json.dumps(message_body)
            # Publish using the default exchange with routing key as queue name
            await channel.default_exchange.publish(
                aio_pika.Message(
                    body=message_json.encode("utf-8"),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=self.queue_name,
            )
            logger.info(
                f"Successfully published reindex job for {repo_full_name}#{pr_number} to queue {self.queue_name}"
            )

    async def consume_reindex_jobs(
        self, callback: Callable[[dict[str, Any]], Awaitable[None]]
    ) -> None:
        """Consume codebase reindexing jobs from RabbitMQ.

        Args:
            callback: Async callback function that processes message body dictionary
        """
        if not self.is_available():
            raise RuntimeError("RabbitMQ service is not available")

        logger.info(
            f"Connecting to RabbitMQ to consume from queue {self.queue_name}..."
        )
        connection = await aio_pika.connect_robust(self.url)
        async with connection:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=1)
            queue = await channel.declare_queue(self.queue_name, durable=True)

            logger.info(f"Worker listening on queue: {self.queue_name}")
            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    # Use message.process(requeue=True) which acks on success and nacks (requeues) on failure
                    async with message.process(requeue=True):
                        try:
                            body_str = message.body.decode("utf-8")
                            message_body = json.loads(body_str)
                            logger.info(f"Processing reindex job: {message_body}")
                            await callback(message_body)
                            logger.info(
                                f"Successfully processed reindex job: {message_body}"
                            )
                        except Exception as e:
                            logger.error(f"Error processing message callback: {e}")
                            raise


rabbitmq_service = RabbitMQService()
