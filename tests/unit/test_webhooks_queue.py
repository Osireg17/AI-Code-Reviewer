import hashlib
import hmac
import json
from types import SimpleNamespace

from src.api import webhooks


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_github_webhook_enqueues_job_and_returns_id(monkeypatch, client, webhook_url):
    secret = "test-secret"  # pragma: allowlist secret
    monkeypatch.setattr(webhooks.settings, "github_webhook_secret", secret)
    monkeypatch.setattr(webhooks, "_active_reviews", set())

    captured: dict[str, object] = {}
    dummy_job = SimpleNamespace(id="job-123")

    def fake_enqueue(repo_name, pr_number, action, priority=None):
        captured["args"] = (repo_name, pr_number, action)
        captured["priority"] = priority
        return dummy_job

    monkeypatch.setattr(webhooks, "enqueue_review", fake_enqueue)

    payload = {
        "action": "opened",
        "pull_request": {
            "number": 42,
            "state": "open",
            "labels": [{"name": "security"}],
            "changed_files": 3,
        },
        "repository": {"full_name": "acme/widgets"},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": _signature(secret, body),
        "Content-Type": "application/json",
    }

    response = client.post(webhook_url, data=body, headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == dummy_job.id
    assert captured["args"] == ("acme/widgets", 42, "opened")
    # security label should elevate priority
    assert captured["priority"] == "high"
