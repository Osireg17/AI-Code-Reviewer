"""Redis-backed queue configuration for PR review jobs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping

from redis import Redis
from rq import Queue, Retry
from rq.exceptions import NoSuchJobError
from rq.job import Job

from src.config.settings import settings

logger = logging.getLogger(__name__)

# Default queue and retry configuration
JOB_TIMEOUT_SECONDS = settings.worker_job_timeout
# RQ's Retry.max is the number of retries in addition to the first attempt.
MAX_ATTEMPTS = 3
RETRY_STRATEGY = Retry(max=MAX_ATTEMPTS - 1, interval=[30, 90, 180])
DEFAULT_PRIORITY = "default"

# Map event actions to priority lanes
PRIORITY_MAPPING: Mapping[str, str] = {
    "opened": "high",
    "reopened": "default",
}

# Single Redis connection used by all queues
if settings.redis_url:
    redis_connection = Redis.from_url(settings.redis_url, socket_timeout=5)
else:
    redis_connection = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        socket_timeout=5,
    )
redis_conn = redis_connection  # alias for worker script imports

# Create queues per priority lane; fall back to default when unmapped
_queues: dict[str, Queue] = {}
for priority in {DEFAULT_PRIORITY, *PRIORITY_MAPPING.values()}:
    queue_name = f"reviews:{priority}"
    _queues[priority] = Queue(queue_name, connection=redis_connection)

# Default queue export for callers that do not need priority control
review_queue = _queues[DEFAULT_PRIORITY]


def get_all_queues() -> list[Queue]:
    """Return all configured queues (one per priority lane)."""
    return list(_queues.values())


def _sanitize_repo(repo_name: str) -> str:
    """Return a Redis-safe repo identifier for job ids (Redis keys disallow ':')."""
    return repo_name.replace(":", "-").replace("/", "__")


def _job_id(repo_name: str, pr_number: int) -> str:
    """Build a deterministic job id for deduplication across workers."""
    safe_repo = _sanitize_repo(repo_name)
    return f"review-{safe_repo}-pr-{pr_number}"


def _get_queue(action: str, priority: str | None = None) -> Queue:
    """Return the queue associated with the action priority or explicit override."""
    if priority and priority in _queues:
        return _queues[priority]
    mapped_priority = PRIORITY_MAPPING.get(action, DEFAULT_PRIORITY)
    return _queues.get(mapped_priority, review_queue)


def _fetch_existing_job(job_id: str) -> Job | None:
    """Attempt to fetch an existing job by id without raising."""
    try:
        return Job.fetch(job_id, connection=redis_connection)
    except NoSuchJobError:
        return None


def run_review_job(repo_name: str, pr_number: int, action: str = "opened") -> None:
    """RQ job entrypoint that executes the async review pipeline."""
    logger.info(
        "Starting review job for %s#%s (action=%s)", repo_name, pr_number, action
    )
    # Deferred import keeps queue config lightweight for non-worker processes
    from src.api.handlers.pr_review_handler import handle_pr_review

    asyncio.run(handle_pr_review(repo_name, pr_number, action))
    logger.info("Finished review job for %s#%s", repo_name, pr_number)


def enqueue_review(
    repo_name: str, pr_number: int, action: str = "opened", priority: str | None = None
) -> Job:
    """Enqueue a PR review job with deduplication, priority, retries, and timeout.

    - Deduplicates by repo/pr pair using a deterministic job id.
    - Routes jobs to priority queues based on the incoming action or override.
    - Applies a 10 minute timeout and 3 total attempts (2 retries).
    """
    job_id = _job_id(repo_name, pr_number)
    queue = _get_queue(action, priority)

    # Deduplicate across queue/worker restarts
    existing_job = _fetch_existing_job(job_id)
    if existing_job:
        status = existing_job.get_status(refresh=True)
        if status in {"queued", "started", "deferred"}:
            logger.info(
                "Skipping duplicate review job for %s#%s (status=%s)",
                repo_name,
                pr_number,
                status,
            )
            return existing_job

    logger.info(
        "Enqueuing review job for %s#%s on queue '%s' (action=%s, priority=%s)",
        repo_name,
        pr_number,
        queue.name,
        action,
        priority or "mapped",
    )
    logger.debug(
        "Enqueue options: timeout=%s, retry=%s, job_id=%s",
        JOB_TIMEOUT_SECONDS,
        RETRY_STRATEGY,
        job_id,
    )
    job = queue.enqueue(
        run_review_job,
        repo_name,
        pr_number,
        action,
        job_id=job_id,
        retry=RETRY_STRATEGY,
        job_timeout=JOB_TIMEOUT_SECONDS,
    )
    return job
