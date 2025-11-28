"""Pytest configuration and fixtures."""

import pytest
from fastapi.testclient import TestClient

from src.config.settings import settings
from src.main import app


@pytest.fixture
def client() -> TestClient:
    """Return a FastAPI TestClient."""
    return TestClient(app)


@pytest.fixture
def webhook_url() -> str:
    """Return the webhook URL for testing."""
    return "/webhook/github"


@pytest.fixture
def webhook_secret() -> str:
    """Return the webhook secret for testing."""
    if not settings.github_webhook_secret:
        pytest.skip("GITHUB_WEBHOOK_SECRET not set")
    return settings.github_webhook_secret