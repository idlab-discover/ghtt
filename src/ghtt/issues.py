"""Create and update the milestones and issues described by a YAML template."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal

import typer
import yaml
from github import GithubException
from github.GithubObject import NotSet
from github.Issue import Issue
from github.Milestone import Milestone
from github.Repository import Repository
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
)

from .assignment import AssignmentContext
from .errors import GhttError
from .github import clone_url_for, explain_github_error
from .prompt import Confirmer
from .report import TargetReport
from .student_list import RepositoryTarget
from .templates import render_text

# ==============================================================================
# Template Shape
# ==============================================================================
#
# The template is a YAML list of milestones and issues. It is rendered per
# repository first, so each entry below describes one repository's desired state.


class IssueTemplateError(GhttError):
    """An issue template cannot be read, rendered, or applied."""


class MilestoneSpec(BaseModel):
    """A milestone that should exist in the repository."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["milestone"]
    title: str
    description: str = ""
    due_date: Annotated[
        date | datetime | None,
        # `due date` with a space is the legacy spelling and stays supported.
        Field(validation_alias=AliasChoices("due date", "due-date", "due_date")),
    ] = None


class IssueSpec(BaseModel):
    """An issue that should exist in the repository."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["issue"]
    title: str
    body: str = ""
    milestone: str | None = None
    labels: tuple[str, ...] = ()
    assignees: tuple[str, ...] = ()


type TemplateEntry = Annotated[MilestoneSpec | IssueSpec, Field(discriminator="type")]

ENTRIES = TypeAdapter(list[TemplateEntry])


def load_issue_template(path: Path) -> str:
    """Read the issue template before any repository is contacted."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise IssueTemplateError(f"Issue template not found: {path}") from error
    except OSError as error:
        raise IssueTemplateError(
            f"Cannot read issue template {path}: {error}"
        ) from error


def parse_entries(rendered: str, path: Path, target_name: str) -> list[TemplateEntry]:
    """Turn the rendered template of one repository into validated entries."""
    try:
        raw_entries = yaml.safe_load(rendered)
    except yaml.YAMLError as error:
        raise IssueTemplateError(
            f"Issue template {path} is not valid YAML after rendering it for "
            f"{target_name}: {error}"
        ) from error

    if not isinstance(raw_entries, list) or not raw_entries:
        raise IssueTemplateError(
            f"Issue template {path} must contain a non-empty YAML list of "
            "milestones and issues."
        )

    try:
        entries = ENTRIES.validate_python(raw_entries)
    except ValidationError as error:
        raise IssueTemplateError(f"Invalid issue template {path}: {error}") from error

    # A referenced milestone that the template does not define must already exist
    # in the repository; that is checked against the repository further below.
    return entries


def due_datetime(due: date | datetime | None) -> datetime | None:
    """Interpret a template due date in the timezone of the machine running ghtt.

    A date without a time means midnight local time, which is what a teacher
    writing "2026-03-09" in a course template means by it.
    """
    if due is None:
        return None
    if not isinstance(due, datetime):
        due = datetime.combine(due, datetime.min.time())
    if due.tzinfo is None:
        return due.astimezone()
    return due


# ==============================================================================
# create-issues
# ==============================================================================


def create_issues(
    context: AssignmentContext, path: Path, assume_yes: bool
) -> TargetReport:
    """Bring the milestones and issues of every selected repository up to date."""
    settings = context.settings
    template_text = load_issue_template(path)
    confirmer = Confirmer("create the issues for", assume_yes, settings.dry_run)

    typer.secho(f"# Creating issues defined in {path}", fg=typer.colors.GREEN)

    processed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    for target in context.targets:
        repository = context.existing(target)
        if repository is None:
            typer.secho(
                f"Warning: repository {target.name} does not exist; skipping.",
                fg=typer.colors.YELLOW,
                err=True,
            )
            failed.append(f"{target.name}: repository does not exist")
            continue

        if not confirmer.should_proceed(target.url):
            skipped.append(target.name)
            continue

        # Rendering per repository is the point of the template: each one names
        # its own students, group, and clone URL.
        clone_url = clone_url_for(repository, settings.transport)
        entries = parse_entries(
            render_text(template_text, target, clone_url), path, target.name
        )

        try:
            apply_entries(repository, target, entries, settings.dry_run)
        except GithubException as error:
            explained = explain_github_error(error, "update issues of", target.name)
            typer.secho(f"Warning: {explained}", fg=typer.colors.YELLOW, err=True)
            failed.append(f"{target.name}: {explained}")
            continue

        if settings.dry_run:
            skipped.append(target.name)
        else:
            processed.append(target.name)

    return TargetReport(
        processed=tuple(processed), skipped=tuple(skipped), failed=tuple(failed)
    )


def apply_entries(
    repository: Repository,
    target: RepositoryTarget,
    entries: list[TemplateEntry],
    dry_run: bool,
) -> None:
    """Create or update each milestone and issue of one repository.

    Both listings are fetched once per repository. Resolving a milestone or
    finding an existing issue then costs nothing, no matter how many entries the
    template holds.
    """
    typer.secho(f"Updating issues in {target.name}", fg=typer.colors.GREEN)

    milestones = {
        milestone.title: milestone
        for milestone in repository.get_milestones(state="all")
    }
    issues: dict[str, Issue] = {}
    for issue in repository.get_issues(state="all"):
        issues.setdefault(issue.title, issue)

    # Validating references before mutating means a typo in a milestone name
    # cannot leave a repository half updated.
    defined = {entry.title for entry in entries if isinstance(entry, MilestoneSpec)}
    for entry in entries:
        if isinstance(entry, IssueSpec) and entry.milestone is not None:
            if entry.milestone not in defined and entry.milestone not in milestones:
                raise IssueTemplateError(
                    f"Issue {entry.title!r} refers to milestone "
                    f"{entry.milestone!r}, which the template does not define and "
                    f"{target.name} does not have."
                )

    for entry in entries:
        if isinstance(entry, MilestoneSpec):
            apply_milestone(repository, entry, milestones, dry_run)
        else:
            apply_issue(repository, entry, milestones, issues, dry_run)


def apply_milestone(
    repository: Repository,
    entry: MilestoneSpec,
    milestones: dict[str, Milestone],
    dry_run: bool,
) -> None:
    """Create the milestone, or update it when the desired state differs."""
    due_on = due_datetime(entry.due_date)
    existing = milestones.get(entry.title)

    if existing is None:
        if dry_run:
            typer.echo(f"would add milestone '{entry.title}'")
            return
        typer.secho(f"Adding milestone '{entry.title}'", fg=typer.colors.GREEN)
        milestones[entry.title] = repository.create_milestone(
            title=entry.title,
            description=entry.description,
            due_on=due_on if due_on else NotSet,
        )
        return

    # GitHub stores a milestone due date as a day, not an instant, and hands it
    # back at its own time of day. Comparing the day is what keeps an unchanged
    # milestone from being rewritten on every run.
    same_due_date = (existing.due_on is None and due_on is None) or (
        existing.due_on is not None
        and due_on is not None
        and existing.due_on.date() == due_on.date()
    )
    if (existing.description or "") == entry.description and same_due_date:
        typer.secho(
            f"Skipping up-to-date milestone '{entry.title}'", fg=typer.colors.GREEN
        )
        return

    if dry_run:
        typer.echo(f"would update milestone '{entry.title}'")
        return
    typer.secho(f"Updating milestone '{entry.title}'", fg=typer.colors.GREEN)
    existing.edit(
        title=entry.title,
        description=entry.description,
        due_on=due_on if due_on else NotSet,
    )


def apply_issue(
    repository: Repository,
    entry: IssueSpec,
    milestones: dict[str, Milestone],
    issues: dict[str, Issue],
    dry_run: bool,
) -> None:
    """Create the issue, or update it when the desired state differs."""
    milestone = milestones.get(entry.milestone) if entry.milestone else None
    existing = issues.get(entry.title)

    if existing is None:
        if dry_run:
            typer.echo(f"would add issue '{entry.title}'")
            return
        typer.secho(f"Adding issue '{entry.title}'", fg=typer.colors.GREEN)
        create_issue_with_assignees(repository, entry, milestone)
        return

    same_body = (existing.body or "") == entry.body
    same_labels = sorted(label.name for label in existing.labels) == sorted(
        entry.labels
    )
    same_assignees = sorted(user.login for user in existing.assignees) == sorted(
        entry.assignees
    )
    same_milestone = (
        existing.milestone.title if existing.milestone else None
    ) == entry.milestone

    if same_body and same_labels and same_assignees and same_milestone:
        typer.secho(f"Skipping up-to-date issue '{entry.title}'", fg=typer.colors.GREEN)
        return

    if dry_run:
        typer.echo(f"would update issue '{entry.title}'")
        return
    typer.secho(f"Updating issue '{entry.title}'", fg=typer.colors.GREEN)
    existing.edit(
        title=entry.title,
        body=entry.body,
        milestone=milestone,
        labels=list(entry.labels),
        assignees=list(entry.assignees),
    )


def create_issue_with_assignees(
    repository: Repository, entry: IssueSpec, milestone: Milestone | None
) -> None:
    """Create an issue, retrying without assignees if GitHub rejects one of them.

    GitHub refuses the whole issue when an assignee has no access to the
    repository, which used to lose the assignment text along with the
    assignment. The issue itself is worth more than its assignees, so it is
    created without them and the problem is reported instead.
    """
    arguments = {
        "title": entry.title,
        "body": entry.body,
        "labels": list(entry.labels),
    }
    if milestone is not None:
        arguments["milestone"] = milestone

    try:
        repository.create_issue(assignees=list(entry.assignees), **arguments)
        return
    except GithubException as error:
        if not entry.assignees or error.status not in {404, 422}:
            raise
        typer.secho(
            f"Warning: {', '.join(entry.assignees)} cannot be assigned on "
            f"{repository.name}; they may have no GitHub account or no access to "
            "the repository. Creating the issue without assignees.",
            fg=typer.colors.YELLOW,
            err=True,
        )

    repository.create_issue(**arguments)
