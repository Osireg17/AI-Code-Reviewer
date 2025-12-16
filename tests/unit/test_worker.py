from types import SimpleNamespace

import worker


def test_health_check_returns_false_on_failure(monkeypatch):
    class BrokenRedis:
        def ping(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(worker, "redis_conn", BrokenRedis())
    assert worker.health_check() is False


def test_start_worker_uses_configured_queues(monkeypatch):
    captured = {}

    def fake_setup_observability():
        captured["setup_called"] = True

    queues = [
        SimpleNamespace(name="reviews:default"),
        SimpleNamespace(name="reviews:high"),
    ]
    monkeypatch.setattr(worker, "get_all_queues", lambda: queues)
    monkeypatch.setattr(worker, "redis_conn", SimpleNamespace(ping=lambda: True))
    monkeypatch.setattr(worker, "setup_observability", fake_setup_observability)

    class DummyWorker:
        def __init__(self, queues, connection=None, name=None, worker_ttl=None, **_):
            self.queues = queues
            self.connection = connection
            self.name = name
            self.worker_ttl = worker_ttl
            self.work_called = False
            captured["worker_name"] = name
            captured["ttl"] = worker_ttl

        def work(self, with_scheduler=True, logging_level=None):
            self.work_called = True
            captured["with_scheduler"] = with_scheduler
            captured["logging_level"] = logging_level
            return "started"

    monkeypatch.setattr(worker, "Worker", DummyWorker)
    # Force start_worker to run the work loop once (dummy returns immediately)
    result = worker.start_worker(run=True)

    assert captured["setup_called"] is True
    assert captured["worker_name"] == worker.settings.worker_name
    assert result.work_called is True
    assert captured["with_scheduler"] == worker.settings.worker_with_scheduler
    assert captured["ttl"] == worker.settings.worker_job_timeout + 60
