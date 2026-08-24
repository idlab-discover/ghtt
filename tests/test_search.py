"""Code search deduplicates repositories and keeps mail credentials private."""

from __future__ import annotations

from typing import Any, cast

import pytest
import requests
import typer
from github import Github

from ghtt.search import (
    SearchError,
    mailgun_settings,
    matching_repositories,
    notify,
    run_search,
)

from .fake_github import FakeGithub, FakeRepository, FakeSearchResult


def test_repeated_code_hits_yield_one_repository() -> None:
    repository = FakeRepository("ada-solution")
    client = FakeGithub(
        search_results=[
            FakeSearchResult(repository),
            FakeSearchResult(repository),
            FakeSearchResult(FakeRepository("bert-solution")),
        ]
    )

    repositories = matching_repositories(cast(Github, client), "Allkit.h in:path")

    assert [repository.name for repository in repositories] == [
        "ada-solution",
        "bert-solution",
    ]
    assert client.searches == 1


def test_each_repository_costs_one_commit_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository("ada-solution")
    client = FakeGithub(
        search_results=[FakeSearchResult(repository), FakeSearchResult(repository)]
    )
    printed: list[str] = []
    monkeypatch.setattr(
        typer, "echo", lambda message="", **_: printed.append(str(message))
    )
    monkeypatch.setattr(
        typer, "secho", lambda message="", **_: printed.append(str(message))
    )
    monkeypatch.setattr("ghtt.search.connect_github", lambda *_: cast(Github, client))

    run_search("https://github.example.edu", "token", "Allkit.h in:path", None)

    assert repository.request_count == 1
    assert any("ada@example.edu" in line for line in printed)


def test_search_without_results_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeGithub(search_results=[])
    printed: list[str] = []
    monkeypatch.setattr(
        typer, "echo", lambda message="", **_: printed.append(str(message))
    )
    monkeypatch.setattr(
        typer, "secho", lambda message="", **_: printed.append(str(message))
    )
    monkeypatch.setattr("ghtt.search.connect_github", lambda *_: cast(Github, client))

    run_search("https://github.example.edu", "token", "nothing in:path", None)

    assert "no results" in printed


def test_partial_mail_settings_are_rejected() -> None:
    with pytest.raises(SearchError, match="together"):
        mailgun_settings("key", "mg.example.edu", None)


def test_absent_mail_settings_disable_notification() -> None:
    assert mailgun_settings(None, None, None) is None


def test_mailgun_failures_never_echo_the_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = mailgun_settings("secret-key", "mg.example.edu", "teacher@example.edu")
    assert settings is not None

    def failing_post(*_: Any, **__: Any) -> Any:
        raise requests.RequestException("connection refused")

    monkeypatch.setattr(requests, "post", failing_post)

    with pytest.raises(SearchError) as error:
        notify(settings, "Allkit.h in:path", ["https://github.example.edu/course/ada"])

    assert "secret-key" not in str(error.value)
    assert "Mailgun rejected the notification" in str(error.value)
