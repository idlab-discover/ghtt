"""Fetch every student repository into a local branch and summarize its last commit."""

from __future__ import annotations

from datetime import datetime

import typer
from pydantic import BaseModel, ConfigDict
from tabulate import tabulate

from .assignment import AssignmentContext, require_source
from .git import GitError, fetch_into_branch, latest_commit
from .github import clone_url_for
from .prompt import Confirmer
from .report import TargetReport

# ==============================================================================
# Summary Rows
# ==============================================================================


class PullRow(BaseModel):
    """One line of the table that `pull` prints when it is done."""

    model_config = ConfigDict(frozen=True)

    repository: str
    description: str
    committed_at: datetime | None
    committer: str
    summary: str

    def sort_key(self) -> datetime:
        """Order by commit time, keeping rows without one at the top."""
        return self.committed_at or datetime.min


# ==============================================================================
# pull
# ==============================================================================


def pull_repositories(
    context: AssignmentContext, force: bool, assume_yes: bool
) -> TargetReport:
    """Fetch each selected repository into a local branch named after it.

    Nothing is checked out: the fetched work lands on its own branch so the
    caller's worktree, and every branch that is not a target, are left alone.
    Use `ghtt util branches-to-folders` afterwards to unpack the branches.
    """
    settings = context.settings
    source = require_source(settings)
    confirmer = Confirmer("pull", assume_yes, settings.dry_run)

    rows: list[PullRow] = []
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
            rows.append(
                PullRow(
                    repository=target.name,
                    description=target.description,
                    committed_at=None,
                    committer="",
                    summary="pull failed: repository not found",
                )
            )
            failed.append(f"{target.name}: repository does not exist")
            continue

        if not confirmer.should_proceed(target.url):
            skipped.append(target.name)
            continue

        if settings.dry_run:
            typer.echo(f"would fetch {target.url} into local branch {target.name}")
            skipped.append(target.name)
            continue

        typer.secho(f"Fetching {target.name}", fg=typer.colors.GREEN)
        try:
            fetch_into_branch(
                source,
                clone_url_for(repository, settings.transport),
                "HEAD",
                target.name,
                settings.transport,
                settings.git_token,
                force=force,
            )
            committed_at, committer, summary = latest_commit(source, target.name)
        except GitError as error:
            # One unreachable repository must not cost the summary of the rest,
            # so the failure becomes a row of the table like any other result.
            typer.secho(
                f"Warning: could not fetch {target.name}: {error}\n"
                "If the local branch has diverged, rerun with --force to replace it.",
                fg=typer.colors.YELLOW,
                err=True,
            )
            rows.append(
                PullRow(
                    repository=target.name,
                    description=repository.description or "",
                    committed_at=None,
                    committer="",
                    summary="pull failed: see the warning above",
                )
            )
            failed.append(f"{target.name}: fetch failed")
            continue

        rows.append(
            PullRow(
                repository=target.name,
                description=repository.description or "",
                committed_at=datetime.fromtimestamp(committed_at),
                committer=committer,
                summary=summary,
            )
        )
        processed.append(target.name)

    show_summary(rows)
    return TargetReport(
        processed=tuple(processed), skipped=tuple(skipped), failed=tuple(failed)
    )


def show_summary(rows: list[PullRow]) -> None:
    """Print the pull summary sorted by commit time, oldest work first."""
    if not rows:
        return
    typer.echo("")
    typer.echo(
        tabulate(
            [
                (
                    row.repository,
                    row.description,
                    row.committed_at.isoformat(" ", "seconds")
                    if row.committed_at
                    else "",
                    row.committer,
                    row.summary,
                )
                for row in sorted(rows, key=PullRow.sort_key)
            ],
            headers=[
                "Repository",
                "Description",
                "Last commit time",
                "Committer info",
                "Commit summary",
            ],
        )
    )
