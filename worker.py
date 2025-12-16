"""RQ worker entrypoint for processing PR review jobs."""

from __future__ import annotations

import logging
import sys

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


def start_worker(run: bool = True) -> Worker:
    """Create and optionally start the RQ worker."""
    setup_observability()

    queues = get_all_queues()
    if not queues:
        logger.error("No queues configured; aborting worker startup")
        sys.exit(1)

    logger.info(
        "Starting worker '%s' for queues: %s",
        settings.worker_name,
        ", ".join(q.name for q in queues),
    )
    worker = Worker(
        queues=queues,
        connection=redis_conn,
        name=settings.worker_name,
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
            logger.info("Worker '%s' exited cleanly", settings.worker_name)

    return worker


if __name__ == "__main__":
    start_worker(run=True)
