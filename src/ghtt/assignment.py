"""Shared preparation for every command that acts on student repositories.

All assignment commands answer the same three questions before they mutate
anything: which repositories are targeted, do those repositories look sane, and
which of them already exist on GitHub. This module answers them once.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from github.Organization import Organization
from github.Repository import Repository
from pydantic import BaseModel, ConfigDict, SkipValidation
from tabulate import tabulate

from .config import ConfigError
from .git import require_git_repository
from .github import connect_github, load_organization, load_repositories
from .prompt import Confirmer
from .settings import Settings
from .student_list import (
    Person,
    RepositoryTarget,
    StudentListError,
    build_targets,
    load_student_list,
    parse_filter,
)

# ==============================================================================
# Command Input And Results
# ==============================================================================


class TargetSelection(BaseModel):
    """The ``--students`` and ``--groups`` filters as typed on the command line.

    Both are filters over the configured student list, never a substitute for
    it: a target is kept when it satisfies every filter that was supplied.
    """

    model_config = ConfigDict(frozen=True)

    students: str | None = None
    groups: str | None = None
    assume_yes: bool = False


class AssignmentContext(BaseModel):
    """Everything an assignment command needs after preparation succeeds."""

    # PyGithub objects are live API handles rather than values to validate, so
    # they are carried as-is. Skipping validation is what lets the test suite
    # substitute a recording stand-in for the real API.
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    settings: Settings
    organization: Annotated[Organization, SkipValidation]
    repositories: Annotated[dict[str, Repository], SkipValidation]
    targets: tuple[RepositoryTarget, ...]

    def existing(self, target: RepositoryTarget) -> Repository | None:
        """Look a target up in the organization listing fetched during preparation."""
        return self.repositories.get(target.name.lower())


# ==============================================================================
# Preparation
# ==============================================================================


def prepare_assignment(
    settings: Settings, selection: TargetSelection
) -> AssignmentContext:
    """Derive the target plan from resolved settings, validate it, and show it.

    Settings are resolved by the caller so that a command such as
    ``delete-repos`` can check its own safeguards before anything is selected.
    """
    if settings.config.students is None:
        raise ConfigError(
            "Missing student list. Supply --students-file and "
            "--student-username-field, or set students.source in the config file."
        )

    students = load_student_list(settings.config.students, role="student")
    mentors: tuple[Person, ...] = ()
    if settings.config.mentors is not None:
        mentors = load_student_list(settings.config.mentors, role="mentor")

    targets = build_targets(
        settings.config,
        organization=settings.connection.organization,
        students=students,
        mentors=mentors,
        student_filter=parse_filter(selection.students, option="--students"),
        group_filter=parse_filter(selection.groups, option="--groups"),
        github_url=settings.connection.git_url,
    )
    if not targets:
        raise StudentListError(
            "No repositories match the selected students and groups. "
            "Check --students, --groups, and the configured student list."
        )

    show_plan(targets)
    targets = confirm_group_sizes(settings, targets, selection.assume_yes)

    # Connecting last keeps every data error offline and instant, which is what
    # makes a mistyped filter cheap to discover.
    typer.secho(
        f"# Listing the repositories of {settings.connection.organization}..",
        fg=typer.colors.GREEN,
    )
    client = connect_github(settings.connection, settings.token)
    organization = load_organization(client, settings.connection.organization)
    repositories = load_repositories(organization)

    return AssignmentContext(
        settings=settings,
        organization=organization,
        repositories=repositories,
        targets=targets,
    )


def require_source(settings: Settings) -> Path:
    """Return the source repository, checking that it is one before anything runs.

    ``create-repos``, ``create-pr``, and ``pull`` all work from a local Git
    repository, and all three must fail before they touch GitHub if it is
    missing or is an ordinary directory.
    """
    source = settings.config.source
    if source is None:
        raise ConfigError(
            "Missing source repository. Supply it with --source or set 'source' "
            "in the config file."
        )
    require_git_repository(source)
    return source


def show_plan(targets: tuple[RepositoryTarget, ...]) -> None:
    """Print the deterministic plan a command is about to act on."""
    rows = [
        (
            target.name,
            target.group or "-",
            ", ".join(student.username for student in target.students),
            ", ".join(mentor.username for mentor in target.mentors) or "-",
        )
        for target in targets
    ]
    typer.secho(f"# {len(targets)} repositories selected:", fg=typer.colors.GREEN)
    typer.echo(tabulate(rows, headers=["Repository", "Group", "Students", "Mentors"]))
    typer.echo("")


def confirm_group_sizes(
    settings: Settings,
    targets: tuple[RepositoryTarget, ...],
    assume_yes: bool,
) -> tuple[RepositoryTarget, ...]:
    """Drop targets whose group does not have the expected people, unless confirmed.

    A wrong group is almost always a mistake in the student list rather than an
    intent, so an unexpected size stops that one repository instead of the run.
    An expected count of zero disables its own check.
    """
    expected_students = settings.config.expected_group_size
    expected_mentors = settings.config.expected_mentors_per_group
    if not expected_students and not expected_mentors:
        return targets

    confirmer = Confirmer(
        "proceed with the unexpected group", assume_yes, settings.dry_run
    )
    accepted: list[RepositoryTarget] = []
    for target in targets:
        wrong_students = expected_students and len(target.students) != expected_students
        wrong_mentors = expected_mentors and len(target.mentors) != expected_mentors
        if not wrong_students and not wrong_mentors:
            accepted.append(target)
            continue

        typer.secho(
            f"Repository {target.name} has {len(target.students)} students and "
            f"{len(target.mentors)} mentors "
            f"(expected {expected_students}/{expected_mentors}):",
            fg=typer.colors.YELLOW,
        )
        for student in target.students:
            typer.echo(f"   - student {student.username} ({student.comment})")
        for mentor in target.mentors:
            typer.echo(f"   - mentor {mentor.username} ({mentor.comment})")
        if confirmer.should_proceed(target.name):
            accepted.append(target)
    return tuple(accepted)
