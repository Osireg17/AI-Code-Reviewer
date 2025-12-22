"""RQ worker entrypoint for processing PR review jobs."""

from __future__ import annotations

import logging
import os
import sys
import uuid

from redis.exceptions import ConnectionError
from rq import Worker

from src.config.settings import settings
from src.queue.config import get_all_queues, redis_conn
from src.utils.logging import setup_observability

logger = logging.getLogger(__name__)


def health_check() -> bool:
    """Return True if Redis is reachable."""
    try:
        return bool(redis_conn.ping())
    except Exception:
        logger.exception("Worker health check failed (Redis unreachable)")
        return False


def cleanup_stale_workers() -> None:
    """Remove stale worker registrations from Redis."""
    try:
        workers = Worker.all(connection=redis_conn)
        for worker in workers:
            # Clean up workers that match our base name but are no longer alive
            if worker.name.startswith(settings.worker_name) and worker.state in (
                "dead",
                "failed",
            ):
                logger.info(
                    "Cleaning up stale worker: %s (state=%s)", worker.name, worker.state
                )
                worker.register_death()
    except Exception:
        logger.exception("Failed to cleanup stale workers")


def get_unique_worker_name() -> str:
    """Generate a unique worker name using hostname and UUID."""
    # Use Railway's RAILWAY_REPLICA_ID if available, otherwise hostname + short UUID
    replica_id = os.getenv("RAILWAY_REPLICA_ID")
    if replica_id:
        return f"{settings.worker_name}-{replica_id}"

    hostname = os.getenv("HOSTNAME", "local")
    short_uuid = str(uuid.uuid4())[:8]
    return f"{settings.worker_name}-{hostname}-{short_uuid}"


def start_worker(run: bool = True) -> Worker:
    """Create and optionally start the RQ worker."""
    setup_observability()

    # Clean up any stale workers before starting
    cleanup_stale_workers()

    queues = get_all_queues()
    if not queues:
        logger.error("No queues configured; aborting worker startup")
        sys.exit(1)

    # Generate unique worker name to avoid collisions
    worker_name = get_unique_worker_name()

    logger.info(
        "Starting worker '%s' for queues: %s",
        worker_name,
        ", ".join(q.name for q in queues),
    )
    worker = Worker(
        queues=queues,
        connection=redis_conn,
        name=worker_name,
        worker_ttl=settings.worker_job_timeout + 60,
    )

    if run:
        try:
            worker.work(
                with_scheduler=settings.worker_with_scheduler,
                logging_level=getattr(logging, settings.log_level),
            )
        except ConnectionError:
            logger.exception("Failed to start worker: Redis connection error")
            sys.exit(1)
        except Exception:
            logger.exception("Worker terminated due to unexpected error")
            sys.exit(1)
        else:
            logger.info("Worker '%s' exited cleanly", worker_name)

    return worker


if __name__ == "__main__":
    start_worker(run=True)
