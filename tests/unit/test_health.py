from types import SimpleNamespace

from src import main


def test_health_includes_queue_metrics(monkeypatch, client):
    monkeypatch.setattr(main, "redis_conn", SimpleNamespace(ping=lambda: True))
    monkeypatch.setattr(main, "review_queue", SimpleNamespace(count=7))
    monkeypatch.setattr(
        main, "Worker", SimpleNamespace(all=lambda connection=None: [1, 2])
    )

    response = client.get("/health")
    data = response.json()

    assert response.status_code == 200
    assert data["redis_connected"] is True
    assert data["queue_size"] == 7
    assert data["active_workers"] == 2
