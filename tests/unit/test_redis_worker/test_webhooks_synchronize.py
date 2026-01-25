"""Unit tests for webhook synchronize event handling."""

import hashlib
import hmac
import json
from types import SimpleNamespace

from src.api import webhooks
from src.api.handlers import webhook_event_handlers


def _signature(secret: str, body: bytes) -> str:
    """Generate HMAC signature for webhook payload."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class TestSynchronizeEventHandling:
    """Tests for synchronize event processing in webhook handler."""

    def test_synchronize_event_queues_review_job(
        self, monkeypatch, client, webhook_url
    ):
        """Test that synchronize events queue a review job."""
        secret = "test-secret"  # pragma: allowlist secret
        monkeypatch.setattr(webhooks.settings, "github_webhook_secret", secret)

        captured = {}
        dummy_job = SimpleNamespace(id="sync-job-456")

        def fake_enqueue(
            repo_name, pr_number, action, priority=None, force_full_review=False
        ):
            captured["args"] = (repo_name, pr_number, action)
            captured["priority"] = priority
            captured["force_full_review"] = force_full_review
            return dummy_job

        monkeypatch.setattr(webhook_event_handlers, "enqueue_review", fake_enqueue)

        payload = {
            "action": "synchronize",
            "pull_request": {
                "number": 42,
                "state": "open",
                "labels": [],
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
        assert data["status"] == "accepted"
        assert data["job_id"] == dummy_job.id
        assert captured["args"] == ("acme/widgets", 42, "synchronize")
        assert captured["force_full_review"] is False

    def test_synchronize_uses_default_priority(self, monkeypatch, client, webhook_url):
        """Test synchronize events get default priority."""
        secret = "test-secret"  # pragma: allowlist secret
        monkeypatch.setattr(webhooks.settings, "github_webhook_secret", secret)

        captured = {}
        dummy_job = SimpleNamespace(id="job-789")

        def fake_enqueue(
            repo_name, pr_number, action, priority=None, force_full_review=False
        ):
            captured["priority"] = priority
            return dummy_job

        monkeypatch.setattr(webhook_event_handlers, "enqueue_review", fake_enqueue)

        payload = {
            "action": "synchronize",
            "pull_request": {
                "number": 10,
                "state": "open",
                "labels": [],
                "changed_files": 5,
            },
            "repository": {"full_name": "test/repo"},
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _signature(secret, body),
            "Content-Type": "application/json",
        }

        response = client.post(webhook_url, data=body, headers=headers)

        assert response.status_code == 200
        # synchronize without special labels should get default priority
        assert captured["priority"] == "default"

    def test_synchronize_with_security_label_gets_high_priority(
        self, monkeypatch, client, webhook_url
    ):
        """Test synchronize with security label gets elevated priority."""
        secret = "test-secret"  # pragma: allowlist secret
        monkeypatch.setattr(webhooks.settings, "github_webhook_secret", secret)

        captured = {}
        dummy_job = SimpleNamespace(id="job-security")

        def fake_enqueue(
            repo_name, pr_number, action, priority=None, force_full_review=False
        ):
            captured["priority"] = priority
            return dummy_job

        monkeypatch.setattr(webhook_event_handlers, "enqueue_review", fake_enqueue)

        payload = {
            "action": "synchronize",
            "pull_request": {
                "number": 5,
                "state": "open",
                "labels": [{"name": "security"}],
                "changed_files": 2,
            },
            "repository": {"full_name": "test/repo"},
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _signature(secret, body),
            "Content-Type": "application/json",
        }

        response = client.post(webhook_url, data=body, headers=headers)

        assert response.status_code == 200
        assert captured["priority"] == "high"

    def test_synchronize_with_closed_pr_is_skipped(
        self, monkeypatch, client, webhook_url
    ):
        """Test synchronize on closed PR is skipped."""
        secret = "test-secret"  # pragma: allowlist secret
        monkeypatch.setattr(webhooks.settings, "github_webhook_secret", secret)

        enqueue_called = False

        def fake_enqueue(*args, **kwargs):
            nonlocal enqueue_called
            enqueue_called = True
            return SimpleNamespace(id="should-not-be-called")

        monkeypatch.setattr(webhook_event_handlers, "enqueue_review", fake_enqueue)

        payload = {
            "action": "synchronize",
            "pull_request": {
                "number": 42,
                "state": "closed",  # PR is closed
                "labels": [],
                "changed_files": 1,
            },
            "repository": {"full_name": "test/repo"},
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
        assert data["status"] == "skipped"
        assert not enqueue_called


class TestIssueCommentReReviewTrigger:
    """Tests for issue_comment re-review trigger handling."""

    def test_re_review_trigger_phrase_queues_full_review(
        self, monkeypatch, client, webhook_url
    ):
        """Test trigger phrase queues a full re-review."""
        secret = "test-secret"  # pragma: allowlist secret
        monkeypatch.setattr(webhooks.settings, "github_webhook_secret", secret)
        monkeypatch.setattr(
            webhook_event_handlers.settings, "github_app_bot_login", "ai-reviewer[bot]"
        )
        monkeypatch.setattr(
            webhook_event_handlers.settings,
            "review_trigger_phrases",
            ["@ai-code-reviewer please review again", "/ai-review"],
        )

        captured = {}
        dummy_job = SimpleNamespace(id="re-review-job")

        def fake_enqueue(
            repo_name, pr_number, action, priority=None, force_full_review=False
        ):
            captured["args"] = (repo_name, pr_number, action)
            captured["priority"] = priority
            captured["force_full_review"] = force_full_review
            return dummy_job

        monkeypatch.setattr(webhook_event_handlers, "enqueue_review", fake_enqueue)

        payload = {
            "action": "created",
            "comment": {
                "id": 123,
                "body": "@ai-code-reviewer please review again",
                "user": {"login": "developer", "type": "User"},
            },
            "issue": {
                "number": 42,
                "pull_request": {},  # Indicates this is a PR
            },
            "repository": {"full_name": "acme/widgets"},
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "X-GitHub-Event": "issue_comment",
            "X-Hub-Signature-256": _signature(secret, body),
            "Content-Type": "application/json",
        }

        response = client.post(webhook_url, data=body, headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert captured["args"] == ("acme/widgets", 42, "re-review")
        assert captured["priority"] == "high"
        assert captured["force_full_review"] is True

    def test_slash_command_trigger(self, monkeypatch, client, webhook_url):
        """Test /ai-review slash command triggers re-review."""
        secret = "test-secret"  # pragma: allowlist secret
        monkeypatch.setattr(webhooks.settings, "github_webhook_secret", secret)
        monkeypatch.setattr(
            webhook_event_handlers.settings, "github_app_bot_login", "ai-reviewer[bot]"
        )
        monkeypatch.setattr(
            webhook_event_handlers.settings,
            "review_trigger_phrases",
            ["/ai-review"],
        )

        captured = {}
        dummy_job = SimpleNamespace(id="slash-job")

        def fake_enqueue(
            repo_name, pr_number, action, priority=None, force_full_review=False
        ):
            captured["repo_name"] = repo_name
            captured["pr_number"] = pr_number
            captured["action"] = action
            captured["priority"] = priority
            captured["force_full_review"] = force_full_review
            return dummy_job

        monkeypatch.setattr(webhook_event_handlers, "enqueue_review", fake_enqueue)

        payload = {
            "action": "created",
            "comment": {
                "id": 456,
                "body": "/ai-review",
                "user": {"login": "developer", "type": "User"},
            },
            "issue": {
                "number": 99,
                "pull_request": {},
            },
            "repository": {"full_name": "test/repo"},
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "X-GitHub-Event": "issue_comment",
            "X-Hub-Signature-256": _signature(secret, body),
            "Content-Type": "application/json",
        }

        response = client.post(webhook_url, data=body, headers=headers)

        assert response.status_code == 200
        assert captured.get("force_full_review") is True

    def test_bot_self_comment_ignored(self, monkeypatch, client, webhook_url):
        """Test bot's own comments are ignored to prevent loops."""
        secret = "test-secret"  # pragma: allowlist secret
        monkeypatch.setattr(webhooks.settings, "github_webhook_secret", secret)
        monkeypatch.setattr(
            webhook_event_handlers.settings, "github_app_bot_login", "ai-reviewer[bot]"
        )
        monkeypatch.setattr(
            webhook_event_handlers.settings,
            "review_trigger_phrases",
            ["/ai-review"],
        )

        enqueue_called = False

        def fake_enqueue(*args, **kwargs):
            nonlocal enqueue_called
            enqueue_called = True
            return SimpleNamespace(id="should-not-happen")

        monkeypatch.setattr(webhook_event_handlers, "enqueue_review", fake_enqueue)

        payload = {
            "action": "created",
            "comment": {
                "id": 789,
                "body": "/ai-review",
                "user": {"login": "ai-reviewer[bot]", "type": "Bot"},  # Bot user
            },
            "issue": {
                "number": 42,
                "pull_request": {},
            },
            "repository": {"full_name": "test/repo"},
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "X-GitHub-Event": "issue_comment",
            "X-Hub-Signature-256": _signature(secret, body),
            "Content-Type": "application/json",
        }

        response = client.post(webhook_url, data=body, headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert "ignored" in data["message"].lower()
        assert not enqueue_called

    def test_non_pr_issue_comment_ignored(self, monkeypatch, client, webhook_url):
        """Test comments on regular issues (not PRs) are ignored."""
        secret = "test-secret"  # pragma: allowlist secret
        monkeypatch.setattr(webhooks.settings, "github_webhook_secret", secret)
        monkeypatch.setattr(
            webhook_event_handlers.settings,
            "review_trigger_phrases",
            ["/ai-review"],
        )

        enqueue_called = False

        def fake_enqueue(*args, **kwargs):
            nonlocal enqueue_called
            enqueue_called = True

        monkeypatch.setattr(webhook_event_handlers, "enqueue_review", fake_enqueue)

        payload = {
            "action": "created",
            "comment": {
                "id": 111,
                "body": "/ai-review",
                "user": {"login": "developer", "type": "User"},
            },
            "issue": {
                "number": 42,
                # No "pull_request" key - this is a regular issue
            },
            "repository": {"full_name": "test/repo"},
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "X-GitHub-Event": "issue_comment",
            "X-Hub-Signature-256": _signature(secret, body),
            "Content-Type": "application/json",
        }

        response = client.post(webhook_url, data=body, headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert "not a PR" in data["message"]
        assert not enqueue_called

    def test_comment_without_trigger_ignored(self, monkeypatch, client, webhook_url):
        """Test regular comments without trigger phrase are ignored."""
        secret = "test-secret"  # pragma: allowlist secret
        monkeypatch.setattr(webhooks.settings, "github_webhook_secret", secret)
        monkeypatch.setattr(
            webhook_event_handlers.settings, "github_app_bot_login", "ai-reviewer[bot]"
        )
        monkeypatch.setattr(
            webhook_event_handlers.settings,
            "review_trigger_phrases",
            ["/ai-review"],
        )

        enqueue_called = False

        def fake_enqueue(*args, **kwargs):
            nonlocal enqueue_called
            enqueue_called = True

        monkeypatch.setattr(webhook_event_handlers, "enqueue_review", fake_enqueue)

        payload = {
            "action": "created",
            "comment": {
                "id": 222,
                "body": "LGTM! Great work on this PR.",  # No trigger phrase
                "user": {"login": "developer", "type": "User"},
            },
            "issue": {
                "number": 42,
                "pull_request": {},
            },
            "repository": {"full_name": "test/repo"},
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "X-GitHub-Event": "issue_comment",
            "X-Hub-Signature-256": _signature(secret, body),
            "Content-Type": "application/json",
        }

        response = client.post(webhook_url, data=body, headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert "No trigger phrase" in data["message"]
        assert not enqueue_called
