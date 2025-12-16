"""FastAPI application entry point."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from rq import Worker

from src.api import webhooks
from src.config.settings import settings
from src.database.db import check_db_connection, init_db
from src.queue.config import redis_conn, review_queue
from src.utils.logging import setup_observability

# Setup logging and observability
setup_observability()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup and shutdown events."""
    # Startup
    logger.info(f"Starting AI Code Reviewer in {settings.environment} environment")
    if settings.logfire_token:
        logger.info("Logfire observability enabled")

    # Initialise database tables
    logger.info("Initializing database...")
    init_db()
    check_db_connection()
    logger.info("Database initialized and connected successfully")

    yield

    # Shutdown
    logger.info("Shutting down AI Code Reviewer")


# Create FastAPI app
app = FastAPI(
    title="AI Code Reviewer",
    description="AI-powered GitHub PR code review agent using Pydantic AI and OpenAI",
    version="0.1.0",
    lifespan=lifespan,
)

# Instrument FastAPI with Logfire if configured
if settings.logfire_token:
    import logfire

    logfire.instrument_fastapi(app)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(webhooks.router)


@app.get("/health")
async def health_check() -> dict[str, str | bool | int]:
    """Health check endpoint with configuration status."""
    redis_connected = False
    queue_size = 0
    active_workers = 0
    try:
        redis_connected = bool(redis_conn.ping())
        queue_size = review_queue.count
        active_workers = len(Worker.all(connection=redis_conn))
    except Exception:
        logger.exception(
            "Health check: failed to query Redis/queue state", exc_info=True
        )

    return {
        "status": "healthy",
        "environment": settings.environment,
        "version": "0.1.0",
        "github_app_configured": bool(settings.github_app_id),
        "openai_configured": bool(settings.openai_api_key),
        "logfire_enabled": bool(settings.logfire_token),
        "webhook_secret_configured": bool(settings.github_webhook_secret),
        "redis_connected": redis_connected,
        "queue_size": queue_size,
        "active_workers": active_workers,
    }


@app.get("/database")
async def database() -> dict[str, str | bool]:
    """Database connection health check endpoint."""
    db_connected = check_db_connection()
    return {
        "database_connected": db_connected,
        "database_url": settings.database_url.split("@")[-1],  # Hide credentials
    }


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "message": "AI Code Reviewer API",
        "docs": "/docs",
        "health": "/health",
        "database": "/database",
    }
