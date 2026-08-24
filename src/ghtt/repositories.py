"""Create, delete, and rename the repositories of an organization."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import typer
from github import GithubException
from github.Repository import Repository

from .assignment import AssignmentContext, require_source
from .errors import GhttError
from .git import GitError, clone_branch, commit_all, list_local_branches, push_branch
from .github import (
    clone_url_for,
    connect_github,
    explain_github_error,
    load_organization,
    load_repositories,
)
from .prompt import Confirmer
from .report import TargetReport
from .rulesets import protect_repository
from .settings import Settings
from .student_list import RepositoryTarget
from .templates import (
    ContentPlan,
    RenderError,
    content_sources,
    render_tree,
    validate_content_plan,
    write_content,
)

# ==============================================================================
# create-repos
# ==============================================================================


def create_repositories(
    context: AssignmentContext, assume_yes: bool, content: ContentPlan
) -> TargetReport:
    """Create a private repository per target and seed it from the source repository.

    A content plan adds the files that differ per student or group, such as a
    credential or a dataset that is too large for the student list, to the first
    commit of each repository.
    """
    settings = context.settings
    source = require_source(settings)
    default_branch = settings.config.default_branch
    validate_content_plan(content)

    # Checking the source branch once, before the first repository exists, keeps
    # a misconfigured default branch from leaving empty repositories behind.
    if default_branch not in list_local_branches(source):
        raise GitError(
            f"The source repository {source} has no branch {default_branch!r}. "
            "Name the right branch with --default-branch, or add a line such as "
            "'default-branch: main' to your ghtt.yaml."
        )

    confirmer = Confirmer("create the repository", assume_yes, settings.dry_run)

    processed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    for target in context.targets:
        if context.existing(target) is not None:
            typer.secho(
                f"Repository {target.url} already exists; skipping. "
                "ghtt never overwrites an existing repository.",
                fg=typer.colors.YELLOW,
            )
            skipped.append(target.name)
            continue

        if not confirmer.should_proceed(target.url):
            skipped.append(target.name)
            continue

        if settings.dry_run:
            typer.echo(
                f"would create private repository {target.url} from {source}, "
                f"push branch {default_branch}, and protect every branch"
            )
            # Resolving the content here is what makes a dry run a real
            # rehearsal: a group whose own file is missing is named now,
            # instead of halfway through creating a course.
            if not content.is_empty:
                try:
                    for content_source in content_sources(content, target):
                        typer.echo(f"  would add {content_source.destination}")
                except RenderError as error:
                    typer.secho(
                        f"Warning: no content for {target.name}: {error}",
                        fg=typer.colors.YELLOW,
                        err=True,
                    )
                    failed.append(f"{target.name}: {error}")
                    continue
            skipped.append(target.name)
            continue

        typer.secho(f"Creating repository {target.url}", fg=typer.colors.GREEN)
        try:
            repository = context.organization.create_repo(
                target.name,
                private=True,
                has_issues=settings.config.repos.has_issues,
                has_wiki=settings.config.repos.has_wiki,
                has_downloads=False,
                has_projects=False,
            )
        except GithubException as error:
            explained = explain_github_error(error, "create repository", target.name)
            typer.secho(f"Warning: {explained}", fg=typer.colors.YELLOW, err=True)
            failed.append(f"{target.name}: {explained}")
            continue

        try:
            seed_repository(context, target, repository, source, content)
        except (GitError, RenderError) as error:
            typer.secho(f"Warning: {error}", fg=typer.colors.YELLOW, err=True)
            failed.append(f"{target.name}: {error}")
            continue

        try:
            # One edit call carries both settings that depend on the pushed
            # content, instead of the two round trips the legacy tool made.
            repository.edit(
                default_branch=default_branch, description=target.description
            )
        except GithubException as error:
            explained = explain_github_error(error, "configure repository", target.name)
            typer.secho(f"Warning: {explained}", fg=typer.colors.YELLOW, err=True)
            failed.append(f"{target.name}: {explained}")
            continue

        typer.secho(
            "Protecting every branch so students cannot rewrite history",
            fg=typer.colors.GREEN,
        )
        unapplied = protect_repository(
            repository, settings.config.repos.require_pull_requests
        )
        if unapplied:
            failed.append(
                f"{target.name}: could not apply ruleset {', '.join(unapplied)}"
            )
            continue

        processed.append(target.name)

    return TargetReport(
        processed=tuple(processed), skipped=tuple(skipped), failed=tuple(failed)
    )


def seed_repository(
    context: AssignmentContext,
    target: RepositoryTarget,
    repository: Repository,
    source: Path,
    content: ContentPlan,
) -> None:
    """Fill in the templates of a throwaway copy of the source and push it.

    The rendering happens in a temporary clone so the teacher's own source
    repository never gains a branch, a commit, or a rendered file. Content that
    belongs to this repository alone is added as its own commit, so it stays
    recognizable in the history next to the assignment itself.
    """
    settings = context.settings
    default_branch = settings.config.default_branch
    clone_url = clone_url_for(repository, settings.transport)

    with tempfile.TemporaryDirectory(prefix="ghtt-") as directory:
        workspace = Path(directory) / target.name
        clone_branch(source, default_branch, workspace)
        rendered = render_tree(workspace, target, clone_url)
        if rendered:
            typer.echo(f"Rendered {len(rendered)} template files")
            commit_all(workspace, "fill in templates")

        if not content.is_empty:
            changes = write_content(content, workspace, target, clone_url)
            typer.secho(f"Applying the content to {target.name}", fg=typer.colors.GREEN)
            for change in changes:
                # A replaced file is one the source repository also provides,
                # so it is named rather than folded into a count.
                typer.secho(
                    f"  {change.describe()}",
                    fg=typer.colors.YELLOW if change.replaced else typer.colors.GREEN,
                )
            commit_all(workspace, "add per-repository content")

        typer.secho(f"Pushing {default_branch} to {target.url}", fg=typer.colors.GREEN)
        push_branch(
            workspace,
            clone_url,
            "HEAD",
            default_branch,
            settings.transport,
            settings.git_token,
        )


# ==============================================================================
# delete-repos
# ==============================================================================


class DeletionNotEnabled(GhttError):
    """Repository deletion was requested without both required opt-ins."""


def require_deletion_enabled(settings: Settings, destroy_data: bool) -> None:
    """Check both deletion safeguards before anything is selected or contacted.

    Deleting a student repository destroys work that cannot be recovered, so it
    takes two deliberate and independent statements of intent: one on the
    command line for this run, and one in the project settings for this course.
    """
    typer.secho("*** This command will delete repositories! ***", fg=typer.colors.RED)
    typer.secho("*** It will destroy data irrecoverably! ***", fg=typer.colors.RED)
    typer.secho(
        '\nLifesaver: consider "ghtt assignment rename-repo" to rename '
        "repositories instead of deleting them.\n",
        fg=typer.colors.GREEN,
    )

    if not destroy_data:
        raise DeletionNotEnabled(
            "Add --destroy-data to confirm that this command may destroy data."
        )
    if not settings.config.enable_repo_delete:
        raise DeletionNotEnabled(
            "Add --enable-repo-delete, or the line 'enable-repo-delete: true' to "
            "your ghtt.yaml, to enable the delete-repos command."
        )


def delete_repositories(context: AssignmentContext) -> TargetReport:
    """Delete every selected repository after confirming each one separately."""
    dry_run = context.settings.dry_run
    # --yes deliberately has no effect here: every repository is confirmed on
    # its own, because one wrong answer would destroy a whole course.
    confirmer = Confirmer(
        "permanently delete the repository and all its data at",
        assume_yes=False,
        dry_run=dry_run,
        always_ask=True,
    )

    processed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    for target in context.targets:
        repository = context.existing(target)
        if repository is None:
            typer.secho(
                f"Repository {target.name} does not exist; nothing to delete.",
                fg=typer.colors.YELLOW,
            )
            skipped.append(target.name)
            continue

        if not confirmer.should_proceed(target.url):
            skipped.append(target.name)
            continue

        if dry_run:
            typer.echo(f"would permanently delete {target.url}")
            skipped.append(target.name)
            continue

        typer.secho(f"Deleting repository {target.url}", fg=typer.colors.RED)
        try:
            repository.delete()
        except GithubException as error:
            explained = explain_github_error(error, "delete repository", target.name)
            typer.secho(f"Warning: {explained}", fg=typer.colors.YELLOW, err=True)
            failed.append(f"{target.name}: {explained}")
            continue
        processed.append(target.name)

    return TargetReport(
        processed=tuple(processed), skipped=tuple(skipped), failed=tuple(failed)
    )


# ==============================================================================
# rename-repo
# ==============================================================================


class RenameError(GhttError):
    """A rename pattern or replacement cannot be applied safely."""


def rename_repositories(
    settings: Settings, match: str, replace: str, assume_yes: bool
) -> TargetReport:
    """Rename every organization repository whose name matches a regular expression.

    Unlike the other assignment commands this one deliberately works on the whole
    organization rather than on the student list, because its main use is
    tidying up repositories that the student list no longer describes.
    """
    try:
        pattern = re.compile(match)
    except re.error as error:
        raise RenameError(
            f"Invalid --match regular expression {match!r}: {error}"
        ) from error

    client = connect_github(settings.connection, settings.token)
    organization = load_organization(client, settings.connection.organization)
    # Listing a large organization takes a noticeable while, so say what is
    # happening before waiting on it.
    typer.secho(
        f"# Listing the repositories of {settings.connection.organization}..",
        fg=typer.colors.GREEN,
    )
    repositories = load_repositories(organization)

    # Every rename is planned before any is applied, so a replacement that would
    # collide with an existing repository is caught while nothing has changed.
    planned: list[tuple[str, str]] = []
    for name in sorted(repositories):
        repository = repositories[name]
        if not pattern.match(repository.name):
            continue
        try:
            new_name = pattern.sub(replace, repository.name)
        except re.error as error:
            raise RenameError(
                f"Invalid --replace replacement {replace!r}: {error}"
            ) from error
        if not new_name:
            raise RenameError(
                f"Renaming {repository.name} with {replace!r} would leave it nameless"
            )
        if new_name == repository.name:
            continue
        planned.append((repository.name, new_name))

    if not planned:
        typer.secho(
            f"No repository in {organization.login} matches {match!r}.",
            fg=typer.colors.YELLOW,
        )
        return TargetReport()

    typer.secho(
        f"# {len(planned)} repositories will be renamed:", fg=typer.colors.GREEN
    )
    for old_name, new_name in planned:
        typer.echo(f"  {old_name} -> {new_name}")

    taken = set(repositories)
    confirmer = Confirmer("rename", assume_yes, settings.dry_run)

    processed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    for old_name, new_name in planned:
        if new_name.lower() in taken:
            typer.secho(
                f"Warning: {new_name} already exists in {organization.login}; "
                f"leaving {old_name} alone.",
                fg=typer.colors.YELLOW,
                err=True,
            )
            failed.append(f"{old_name}: {new_name} already exists")
            continue

        if not confirmer.should_proceed(f"{old_name} to {new_name}"):
            skipped.append(old_name)
            continue

        if settings.dry_run:
            typer.echo(f"would rename {old_name} to {new_name}")
            skipped.append(old_name)
            continue

        # Every rename is one API round trip. Saying which one is in flight is
        # what keeps a long run from looking like it has stopped responding.
        typer.secho(f"Renaming {old_name} to {new_name}", fg=typer.colors.GREEN)
        try:
            repositories[old_name.lower()].edit(name=new_name)
        except GithubException as error:
            explained = explain_github_error(error, "rename repository", old_name)
            typer.secho(f"Warning: {explained}", fg=typer.colors.YELLOW, err=True)
            failed.append(f"{old_name}: {explained}")
            continue

        # The new name now occupies a slot, so a later rename cannot collide
        # with it even though the listing was fetched before this run started.
        taken.discard(old_name.lower())
        taken.add(new_name.lower())
        processed.append(f"{old_name} -> {new_name}")

    return TargetReport(
        processed=tuple(processed), skipped=tuple(skipped), failed=tuple(failed)
    )
