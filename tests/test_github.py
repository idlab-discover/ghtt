"""GitHub endpoint parsing and errors are deterministic without API access."""

from __future__ import annotations

from typing import cast

import pytest
from github import Github, GithubException
from github.Organization import Organization
from github.Repository import Repository

from ghtt.config import load_config
from ghtt.git import GitTransport
from ghtt.github import (
    GitHubError,
    clone_url_for,
    explain_github_error,
    load_organization,
    load_repositories,
    parse_github_url,
)


def test_legacy_url_supplies_enterprise_api_endpoint_and_organization() -> None:
    connection = parse_github_url("https://github.example.edu/course-org")

    assert connection.api_url == "https://github.example.edu/api/v3"
    assert connection.git_url == "https://github.example.edu"
    assert connection.organization == "course-org"


def test_explicit_organization_overrides_legacy_url_organization() -> None:
    connection = parse_github_url("github.example.edu/old-org", "course-org")

    assert connection.organization == "course-org"


def test_github_com_uses_pygithub_default_endpoint() -> None:
    connection = parse_github_url("https://github.com", "course-org")

    assert connection.api_url is None
    assert connection.git_url == "https://github.com"
    assert connection.organization == "course-org"


def test_legacy_yaml_url_selects_enterprise_api_and_git_hosts(tmp_path) -> None:
    config_path = tmp_path / "ghtt.yaml"
    config_path.write_text(
        "url: https://github.course.example.edu/algorithms-2026\n",
        encoding="utf-8",
    )

    config = load_config(config_path, tmp_path)
    assert config.url is not None
    connection = parse_github_url(config.url)

    assert connection.api_url == "https://github.course.example.edu/api/v3"
    assert connection.git_url == "https://github.course.example.edu"
    assert connection.organization == "algorithms-2026"


def test_url_requires_an_organization() -> None:
    with pytest.raises(GitHubError, match="Missing organization"):
        parse_github_url("github.example.edu")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "authentication failed"),
        (403, "permission denied"),
        (404, "not found"),
        (422, "returned 422"),
    ],
)
def test_github_errors_name_the_action_and_target(status: int, expected: str) -> None:
    error = GithubException(status, "failure", {})

    translated = explain_github_error(error, "create repository", "course-org/ada")

    assert "create repository course-org/ada" in str(translated)
    assert expected in str(translated)


# ==============================================================================
# Organization access
# ==============================================================================


def test_an_organization_the_token_cannot_see_names_the_action() -> None:
    """Issue #17: an opaque 404 used to surface as a raw PyGithub exception."""

    class RefusingClient:
        def get_organization(self, login: str) -> object:
            raise GithubException(404, "Not Found", {})

    with pytest.raises(GitHubError, match="access organization course-org"):
        load_organization(cast(Github, RefusingClient()), "course-org")


def test_a_forbidden_repository_listing_names_the_permission() -> None:
    class RefusingOrganization:
        login = "course-org"

        def get_repos(self, type: str = "all") -> object:
            raise GithubException(403, "Forbidden", {})

    with pytest.raises(GitHubError, match="permission denied") as error:
        load_repositories(cast(Organization, RefusingOrganization()))

    assert "list repositories in course-org" in str(error.value)


def test_the_clone_url_follows_the_selected_transport() -> None:
    class Repo:
        clone_url = "https://github.example.edu/course/ada.git"
        ssh_url = "git@github.example.edu:course/ada.git"

    repository = cast(Repository, Repo())

    assert clone_url_for(repository, GitTransport.HTTPS).startswith("https://")
    assert clone_url_for(repository, GitTransport.SSH).startswith("git@")
