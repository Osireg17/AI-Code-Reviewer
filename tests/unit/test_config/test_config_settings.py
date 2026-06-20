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


def test_is_production(monkeypatch) -> None:
    settings = Settings(_env_file=None, environment="production")
    assert settings.is_production is True
    assert settings.is_development is False


def test_is_development(monkeypatch) -> None:
    settings = Settings(_env_file=None, environment="development")
    assert settings.is_production is False
    assert settings.is_development is True


def test_is_staging(monkeypatch) -> None:
    settings = Settings(_env_file=None, environment="staging")
    assert settings.is_production is False
    assert settings.is_development is False


def test_apply_default_review_triggers() -> None:
    # Uses default github_app_bot_login = "searchlightai[bot]"
    settings = Settings(_env_file=None)
    assert settings.review_trigger_phrases == [
        "@searchlightai please review again",
        "@searchlightai re-review",
        "/ai-review",
    ]


def test_apply_default_review_triggers_with_custom_bot_login() -> None:
    settings = Settings(_env_file=None, github_app_bot_login="custom-bot[bot]")
    assert settings.review_trigger_phrases == [
        "@custom-bot please review again",
        "@custom-bot re-review",
        "/ai-review",
    ]


def test_apply_default_review_triggers_no_bot_suffix() -> None:
    settings = Settings(_env_file=None, github_app_bot_login="my-bot")
    assert settings.review_trigger_phrases == [
        "@my-bot please review again",
        "@my-bot re-review",
        "/ai-review",
    ]


def test_custom_review_triggers() -> None:
    custom_triggers = ["please re-check", "/scan"]
    settings = Settings(_env_file=None, review_trigger_phrases=custom_triggers)
    assert settings.review_trigger_phrases == custom_triggers
