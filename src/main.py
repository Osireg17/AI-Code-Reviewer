"""FastAPI application entry point."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import logfire
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api import webhooks
from src.config.settings import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Configure Logfire if token is provided
if settings.logfire_token:
    logfire.configure(token=settings.logfire_token)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup and shutdown events."""
    # Startup
    logger.info(f"Starting AI Code Reviewer in {settings.environment} environment")
    if settings.logfire_token:
        logger.info("Logfire observability enabled")

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

# Instrument FastAPI with Logfire
if settings.logfire_token:
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
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "environment": settings.environment,
        "version": "0.1.0",
    }


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "message": "AI Code Reviewer API",
        "docs": "/docs",
        "health": "/health",
    }
