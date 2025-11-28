"""Integration tests for GitHub webhook endpoints."""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient


def generate_signature(payload: dict, secret: str) -> str:
    """Generate GitHub webhook signature.

    Args:
        payload: The JSON payload
        secret: The webhook secret

    Returns:
        The signature in the format 'sha256=...'
    """
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={signature}"


@pytest.fixture
def ping_payload() -> dict:
    """Return a sample ping event payload."""
    return {
        "zen": "Keep it logically awesome.",
        "hook_id": 123456789,
        "hook": {
            "type": "Repository",
            "id": 123456789,
            "name": "web",
            "active": True,
            "events": ["pull_request"],
        },
    }


@pytest.fixture
def pr_opened_payload() -> dict:
    """Return a sample pull request opened event payload."""
    return {
        "action": "opened",
        "number": 1,
        "pull_request": {
            "number": 1,
            "title": "Test PR",
            "state": "open",
            "user": {"login": "testuser"},
            "head": {"ref": "feature-branch", "sha": "abc123"},
            "base": {"ref": "main", "sha": "def456"},
        },
        "repository": {
            "full_name": "testuser/testrepo",
            "name": "testrepo",
        },
    }


def test_ping_event(
    client: TestClient, webhook_url: str, webhook_secret: str, ping_payload: dict
) -> None:
    """Test webhook handles ping events correctly."""
    signature = generate_signature(ping_payload, webhook_secret)

    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "ping",
        "X-Hub-Signature-256": signature,
        "User-Agent": "GitHub-Hookshot/test",
    }

    response = client.post(webhook_url, json=ping_payload, headers=headers)

    assert response.status_code == 200
    assert response.json()["message"] == "pong"


def test_pr_opened_event(
    client: TestClient, webhook_url: str, webhook_secret: str, pr_opened_payload: dict
) -> None:
    """Test webhook handles pull request opened events correctly."""
    signature = generate_signature(pr_opened_payload, webhook_secret)

    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": signature,
        "User-Agent": "GitHub-Hookshot/test",
    }

    response = client.post(webhook_url, json=pr_opened_payload, headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert "PR #1 queued for review" in data["message"]
    assert data["status"] == "processing"


def test_invalid_signature(
    client: TestClient, webhook_url: str, ping_payload: dict
) -> None:
    """Test webhook rejects requests with invalid signatures."""
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "ping",
        "X-Hub-Signature-256": "sha256=invalid_signature",
        "User-Agent": "GitHub-Hookshot/test",
    }

    response = client.post(webhook_url, json=ping_payload, headers=headers)

    assert response.status_code == 401
    assert "Invalid signature" in response.json()["detail"]


def test_missing_signature(
    client: TestClient, webhook_url: str, ping_payload: dict
) -> None:
    """Test webhook rejects requests with missing signatures."""
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "ping",
        "User-Agent": "GitHub-Hookshot/test",
    }

    response = client.post(webhook_url, json=ping_payload, headers=headers)

    assert response.status_code == 401
    assert "Missing X-Hub-Signature-256" in response.json()["detail"]


def test_pr_ignored_event(
    client: TestClient, webhook_url: str, webhook_secret: str, pr_opened_payload: dict
) -> None:
    """Test webhook ignores non-processed PR events."""
    # Change action to something we don't process
    pr_opened_payload["action"] = "closed"
    signature = generate_signature(pr_opened_payload, webhook_secret)

    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": signature,
        "User-Agent": "GitHub-Hookshot/test",
    }

    response = client.post(webhook_url, json=pr_opened_payload, headers=headers)

    assert response.status_code == 200
    assert "ignored" in response.json()["message"].lower()


def test_unsupported_event(
    client: TestClient, webhook_url: str, webhook_secret: str, ping_payload: dict
) -> None:
    """Test webhook handles unsupported event types."""
    signature = generate_signature(ping_payload, webhook_secret)

    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "push",  # Unsupported event
        "X-Hub-Signature-256": signature,
        "User-Agent": "GitHub-Hookshot/test",
    }

    response = client.post(webhook_url, json=ping_payload, headers=headers)

    assert response.status_code == 200
    assert "not supported" in response.json()["message"].lower()