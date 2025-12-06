"""Logging and observability setup using Pydantic Logfire."""

import logging
import sys

from src.config.settings import settings


def setup_logging() -> None:
    """Configure application logging.

    Sets up structured logging with appropriate log levels and format.
    Reduces noise from verbose third-party libraries.
    """
    # Get log level from settings
    log_level = getattr(logging, settings.log_level)

    # Configure basic logging
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
        force=True,  # Reconfigure if already setup
    )

    # Reduce noise from verbose libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def setup_observability() -> None:
    """Setup logging and observability with Logfire instrumentation.

    Configures standard logging and optionally enables Logfire for
    distributed tracing and observability if a token is configured.
    """
    # Setup basic logging first
    setup_logging()

    logger = logging.getLogger(__name__)

    # Try to set up Logfire if token is configured
    if settings.logfire_token:
        try:
            import logfire

            # Configure Logfire with token
            logfire.configure(token=settings.logfire_token)

            # Instrument Pydantic AI agents
            logfire.instrument_pydantic_ai()

            # Instrument httpx for HTTP tracing
            logfire.instrument_httpx()

            logger.info(
                f"Logfire observability enabled for {settings.environment} environment"
            )

        except ImportError:
            logger.warning(
                "Logfire package not installed. Install with: pip install 'pydantic-ai[logfire]'"
            )
        except Exception as e:
            logger.error(f"Failed to setup Logfire observability: {e}")
    else:
        logger.info("Logfire token not configured, skipping observability setup")
