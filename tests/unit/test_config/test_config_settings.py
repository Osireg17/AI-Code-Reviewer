from src.config.settings import Settings


def test_redis_settings_defaults(monkeypatch) -> None:
    monkeypatch.delenv("REDIS_HOST", raising=False)
    monkeypatch.delenv("REDIS_PORT", raising=False)
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)

    settings = Settings(_env_file=None)
    assert settings.redis_host == "localhost"
    assert settings.redis_port == 6379
    assert settings.redis_password is None


def test_redis_settings_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_HOST", "redis.internal")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("REDIS_PASSWORD", "super-secret")

    settings = Settings(_env_file=None)

    assert settings.redis_host == "redis.internal"  # pragma: allowlist secret
    assert settings.redis_port == 6380  # pragma: allowlist secret
    assert settings.redis_password == "super-secret"  # pragma: allowlist secret
