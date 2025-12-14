"""Rate limiting utilities for API calls."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def with_exponential_backoff(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = 5,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    **kwargs: Any,
) -> T:
    """
    Execute a function with exponential backoff retry logic.

    Handles rate limiting (429) and transient errors from OpenAI API.

    Args:
        func: The async function to execute
        *args: Positional arguments to pass to func
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds before first retry
        max_delay: Maximum delay in seconds between retries
        **kwargs: Keyword arguments to pass to func

    Returns:
        The result of the function call

    Raises:
        The last exception if all retries are exhausted
    """
    last_exception = None

    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            error_str = str(e).lower()

            # Check if it's a rate limit error (429) or retriable error
            is_rate_limit = "429" in error_str or "rate limit" in error_str
            is_retriable = (
                is_rate_limit
                or "timeout" in error_str
                or "connection" in error_str
                or "503" in error_str
                or "502" in error_str
            )

            if not is_retriable:
                # Not a retriable error, raise immediately
                logger.error(f"Non-retriable error: {e}")
                raise

            if attempt < max_retries - 1:
                # Calculate delay with exponential backoff
                delay = min(initial_delay * (2**attempt), max_delay)

                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed with {type(e).__name__}: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )

                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"All {max_retries} retry attempts exhausted. Last error: {e}"
                )

    # All retries exhausted
    raise last_exception  # type: ignore


def rate_limit_delay(
    delay_seconds: float = 1.0,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Decorator to add a delay before executing a function.

    Useful for throttling API calls to avoid rate limits.

    Args:
        delay_seconds: Number of seconds to wait before executing

    Returns:
        Decorated function

    Example:
        @rate_limit_delay(2.0)
        async def post_comment():
            # This will wait 2 seconds before executing
            pass
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            await asyncio.sleep(delay_seconds)
            return await func(*args, **kwargs)

        return wrapper

    return decorator


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter for controlling request rate.

    Allows bursts up to bucket capacity while maintaining average rate.
    """

    def __init__(self, rate: float, capacity: float) -> None:
        """
        Initialize rate limiter.

        Args:
            rate: Number of tokens to add per second
            capacity: Maximum bucket capacity (max burst size)
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> None:
        """
        Acquire tokens, waiting if necessary.

        Args:
            tokens: Number of tokens to acquire
        """
        async with self._lock:
            while True:
                now = time.time()
                elapsed = now - self.last_update

                # Add new tokens based on elapsed time
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_update = now

                if self.tokens >= tokens:
                    # We have enough tokens
                    self.tokens -= tokens
                    return

                # Not enough tokens, calculate wait time
                tokens_needed = tokens - self.tokens
                wait_time = tokens_needed / self.rate

                logger.debug(
                    f"Rate limit: waiting {wait_time:.2f}s for {tokens_needed} tokens"
                )
                await asyncio.sleep(wait_time)


# Global rate limiter for OpenAI API
# OpenAI rate limits: ~10,000 TPM (tokens per minute) for tier 1
# We'll be conservative: 50 requests per minute = ~0.83 requests/second
openai_rate_limiter = TokenBucketRateLimiter(
    rate=0.83,  # requests per second
    capacity=10,  # allow bursts up to 10 requests
)
