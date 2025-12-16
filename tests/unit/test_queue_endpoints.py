from types import SimpleNamespace

from src.api import webhooks


def test_queue_status_endpoint(monkeypatch, client):
    secret = "test-secret"  # pragma: allowlist secret
    monkeypatch.setattr(webhooks.settings, "github_webhook_secret", secret)

    fake_queue = SimpleNamespace(count=5)
    started = [SimpleNamespace()] * 2
    finished = [SimpleNamespace()] * 3
    failed = [SimpleNamespace()] * 1
    workers = [SimpleNamespace()] * 4

    monkeypatch.setattr(webhooks, "review_queue", fake_queue)
    monkeypatch.setattr(webhooks, "StartedJobRegistry", lambda queue=None: started)
    monkeypatch.setattr(webhooks, "FinishedJobRegistry", lambda queue=None: finished)
    monkeypatch.setattr(webhooks, "FailedJobRegistry", lambda queue=None: failed)
    monkeypatch.setattr(
        webhooks, "Worker", SimpleNamespace(all=lambda connection=None: workers)
    )
    monkeypatch.setattr(webhooks, "redis_conn", SimpleNamespace())

    response = client.get("/webhook/queue/status")
    data = response.json()
    assert response.status_code == 200
    assert data["queued"] == 5
    assert data["started"] == 2
    assert data["finished"] == 3
    assert data["failed"] == 1
    assert data["active_workers"] == 4


def test_queue_job_endpoint(monkeypatch, client):
    secret = "test-secret"  # pragma: allowlist secret
    monkeypatch.setattr(webhooks.settings, "github_webhook_secret", secret)

    class DummyJob:
        id = "job-1"
        created_at = None
        started_at = None
        ended_at = None

        def __init__(self):
            self.return_value = {"ok": True}

        def get_status(self, refresh=False):
            return "finished"

        def latest_result(self):
            return SimpleNamespace(return_value=self.return_value, traceback=None)

    monkeypatch.setattr(webhooks, "redis_conn", SimpleNamespace())
    monkeypatch.setattr(
        webhooks.Job,
        "fetch",
        classmethod(lambda cls, job_id, connection=None: DummyJob()),
    )

    response = client.get("/webhook/queue/job/job-1")
    assert response.status_code == 200
    assert response.json()["job_id"] == "job-1"


def test_queue_job_not_found(monkeypatch, client):
    secret = "test-secret"  # pragma: allowlist secret
    monkeypatch.setattr(webhooks.settings, "github_webhook_secret", secret)

    monkeypatch.setattr(webhooks, "redis_conn", SimpleNamespace())

    def raise_no_job(cls, job_id, connection=None):
        raise webhooks.NoSuchJobError()

    monkeypatch.setattr(webhooks.Job, "fetch", classmethod(raise_no_job))

    response = client.get("/webhook/queue/job/missing")
    assert response.status_code == 404
    assert "Job not found" in response.json()["detail"]
