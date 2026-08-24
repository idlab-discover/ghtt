"""Builders for the resolved values that command tests act on.

Tests use these instead of running the whole option-resolution path, so a test
about one command's behaviour is not also a test of config precedence.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from github.Organization import Organization
from github.Repository import Repository

from ghtt.assignment import AssignmentContext
from ghtt.config import Config
from ghtt.github import GitHubConnection
from ghtt.settings import Settings
from ghtt.student_list import Person, RepositoryTarget

from .fake_github import FakeOrganization, FakeRepository

ORGANIZATION = "course"
GITHUB_URL = "https://github.example.edu"


def make_settings(config: Config | None = None, dry_run: bool = False) -> Settings:
    """Build the settings of a run against a fictional enterprise instance."""
    return Settings(
        config=config or Config(),
        connection=GitHubConnection(
            api_url=f"{GITHUB_URL}/api/v3",
            git_url=GITHUB_URL,
            organization=ORGANIZATION,
        ),
        token="test-token",
        dry_run=dry_run,
    )


def make_person(username: str, groups: tuple[str, ...] = ()) -> Person:
    return Person(username=username, comment=username.title(), groups=groups, record={})


def make_target(
    name: str,
    students: tuple[str, ...] = (),
    mentors: tuple[str, ...] = (),
    group: str | None = None,
) -> RepositoryTarget:
    return RepositoryTarget(
        name=name,
        organization=ORGANIZATION,
        group=group,
        students=tuple(make_person(username) for username in students),
        mentors=tuple(make_person(username) for username in mentors),
        url=f"{GITHUB_URL}/{ORGANIZATION}/{name}",
    )


def make_context(
    targets: tuple[RepositoryTarget, ...],
    repositories: tuple[FakeRepository, ...] = (),
    settings: Settings | None = None,
    local_root: Path | None = None,
) -> AssignmentContext:
    """Build the context a command receives once preparation has succeeded.

    ``local_root`` backs every repository the organization creates with a real
    bare repository, so a test can inspect what was actually pushed.
    """
    organization = FakeOrganization(ORGANIZATION, list(repositories), local_root)
    return AssignmentContext(
        settings=settings or make_settings(),
        organization=cast(Organization, organization),
        repositories=cast(
            "dict[str, Repository]",
            {repository.name.lower(): repository for repository in repositories},
        ),
        targets=targets,
    )


def recorded_organization(context: AssignmentContext) -> FakeOrganization:
    """Read the recording organization back out of a context built above."""
    assert isinstance(context.organization, FakeOrganization)
    return context.organization
