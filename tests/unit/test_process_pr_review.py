from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.api import webhooks


class DummySession:
    def __init__(self):
        self.closed = False

    def close(self) -> None:
        self.closed = True


class DummyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_process_pr_review_runs_and_closes_session(monkeypatch):
    calls: dict[str, object] = {}

    dummy_session = DummySession()

    def session_factory() -> DummySession:
        return dummy_session

    fake_auth = SimpleNamespace(
        get_installation_access_token=AsyncMock(return_value="token")
    )

    class FakePR:
        number = 1

    class FakeRepo:
        def get_pull(self, pr_number: int):
            calls["pr_number"] = pr_number
            return FakePR()

    class FakeGithub:
        def __init__(self, auth=None):
            calls["auth"] = auth

        def get_repo(self, name: str):
            calls["repo_name"] = name
            return FakeRepo()

    monkeypatch.setattr(webhooks, "Github", FakeGithub)
    monkeypatch.setattr(
        webhooks, "Auth", SimpleNamespace(Token=lambda token: f"token-{token}")
    )
    monkeypatch.setattr(webhooks.httpx, "AsyncClient", lambda timeout: DummyClient())
    monkeypatch.setattr(
        webhooks, "ReviewDependencies", lambda **kwargs: SimpleNamespace(**kwargs)
    )

    monkeypatch.setattr(
        webhooks, "_determine_review_type", AsyncMock(return_value=(False, None, None))
    )
    monkeypatch.setattr(webhooks, "_post_progress_comment_if_needed", AsyncMock())
    monkeypatch.setattr(
        webhooks,
        "_run_code_review_agent",
        AsyncMock(
            return_value=SimpleNamespace(
                total_comments=0, summary=SimpleNamespace(recommendation="approve")
            )
        ),
    )
    monkeypatch.setattr(webhooks, "_post_inline_comments_if_needed", AsyncMock())
    monkeypatch.setattr(webhooks, "_post_summary_review_if_needed", AsyncMock())
    monkeypatch.setattr(webhooks, "_update_review_state", AsyncMock())

    await webhooks.process_pr_review(
        "acme/widgets",
        7,
        action="opened",
        session_factory=session_factory,
        github_auth=fake_auth,
        agent=SimpleNamespace(),
    )

    assert dummy_session.closed
    assert calls["repo_name"] == "acme/widgets"
    assert calls["pr_number"] == 7
    assert calls["auth"] == "token-token"
