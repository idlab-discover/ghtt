"""Push updated assignment code to student repositories and open pull requests."""

from __future__ import annotations

import tempfile
from enum import Enum
from pathlib import Path

import typer
from github import GithubException
from github.Repository import Repository

from .assignment import AssignmentContext, require_source
from .git import (
    GitError,
    clone_remote_branch,
    commit_all,
    list_local_branches,
    push_branch,
    remote_branch_exists,
)
from .github import clone_url_for, explain_github_error
from .prompt import Confirmer
from .report import TargetReport
from .student_list import RepositoryTarget
from .templates import (
    ContentChange,
    ContentPlan,
    RenderError,
    validate_content_plan,
    write_content,
)

# ==============================================================================
# create-pr
# ==============================================================================


def create_pull_requests(
    context: AssignmentContext,
    branch: str,
    title: str,
    body: str,
    branch_already_pushed: bool,
    content: ContentPlan,
    force_push: bool,
    assume_yes: bool,
) -> TargetReport:
    """Open one pull request per target, from a shared branch or a content plan.

    The shared mode pushes the same source branch to every repository, which is
    how a class-wide correction or a new assignment is handed out.

    The content mode branches from each repository's own default branch and
    writes only the files of the content plan into it, resolved and rendered for
    that target. That is what keeps a hand-out from carrying anything else along,
    and it needs no access to the source repository or its history. Rerunning it
    continues the existing branch, so only what changed is committed.
    """
    settings = context.settings
    default_branch = settings.config.default_branch

    if not content.is_empty and branch_already_pushed:
        raise GitError(
            "--content-dir and --content-file push a branch to each repository "
            "separately, so they cannot be combined with --branch-already-pushed."
        )

    # Whatever is the same for every repository is checked once, while nothing
    # has been pushed yet, so a mistyped hand-out path is not rediscovered per
    # student.
    validate_content_plan(content)

    # The content mode never reads the source repository, which is what lets a
    # colleague hand something out without a copy of the assignment template.
    source: Path | None = None
    if content.is_empty and not branch_already_pushed:
        source = require_source(settings)
        if default_branch not in list_local_branches(source):
            raise GitError(
                f"The source repository {source} has no branch {default_branch!r}. "
                "Name the right branch with --default-branch."
            )

    typer.secho(f"# Branch: '{branch}'", fg=typer.colors.GREEN)
    typer.secho(f"# Title: '{title}'", fg=typer.colors.GREEN)
    typer.secho(f"# Message: '{body}'", fg=typer.colors.GREEN)
    typer.secho(f"# Base branch: '{default_branch}'", fg=typer.colors.GREEN)
    if not content.is_empty:
        for described in content.describe():
            typer.secho(f"# Content: {described}", fg=typer.colors.GREEN)
    elif branch_already_pushed:
        typer.secho("# The branch has been pushed already.", fg=typer.colors.GREEN)
    else:
        typer.secho(f"# Source directory: '{source}'", fg=typer.colors.GREEN)

    confirmer = Confirmer("create the pull request for", assume_yes, settings.dry_run)

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

        if settings.dry_run and content.is_empty:
            if not branch_already_pushed:
                typer.echo(f"would push {default_branch} to {target.name}:{branch}")
            typer.echo(
                f"would open a pull request '{title}' on {target.name} "
                f"from {branch} into {default_branch}"
            )
            skipped.append(target.name)
            continue

        clone_url = clone_url_for(repository, settings.transport)
        # A push updates an open pull request by itself, so it counts as acting
        # on the target even when no pull request is opened or edited.
        pushed = False
        content_unchanged = False
        try:
            if not content.is_empty:
                changed = apply_content(
                    context, target, clone_url, content, branch, title, force_push
                )
                content_unchanged = changed is None
                pushed = not content_unchanged and not settings.dry_run
            elif source is not None:
                typer.secho(
                    f"Pushing {default_branch} to {target.name}:{branch}",
                    fg=typer.colors.GREEN,
                )
                push_branch(
                    source,
                    clone_url,
                    default_branch,
                    branch,
                    settings.transport,
                    settings.git_token,
                    force=force_push,
                )
                pushed = True
        except RenderError as error:
            # The plan itself is sound, so this is one target's own file that is
            # missing or unreadable: the other repositories still get theirs.
            typer.secho(
                f"Warning: no content for {target.name}: {error}",
                fg=typer.colors.YELLOW,
                err=True,
            )
            failed.append(f"{target.name}: {error}")
            continue
        except GitError as error:
            # A rejected push is nearly always a branch that moved on remotely,
            # so say what to do rather than only repeating Git's own wording.
            typer.secho(
                f"Warning: could not push to {target.name}: {error}\n"
                "If the branch already exists with different history, rerun with "
                "--force-push to start it over from the default branch.",
                fg=typer.colors.YELLOW,
                err=True,
            )
            failed.append(f"{target.name}: push was rejected")
            continue

        try:
            # Unchanged content leaves nothing new to review, so only an open pull
            # request is brought up to date; none is opened for it. A dry run has
            # already announced the pull request it would open.
            outcome = open_pull_request(
                repository,
                target,
                branch,
                title,
                body,
                default_branch,
                may_create=not content_unchanged and not settings.dry_run,
                dry_run=settings.dry_run,
            )
        except GithubException as error:
            explained = explain_github_error(
                error, "create a pull request on", target.name
            )
            typer.secho(f"Warning: {explained}", fg=typer.colors.YELLOW, err=True)
            failed.append(f"{target.name}: {explained}")
            continue

        if settings.dry_run:
            skipped.append(target.name)
        elif pushed or outcome is not PullRequestOutcome.UNCHANGED:
            processed.append(target.name)
        else:
            if content_unchanged:
                typer.secho(
                    f"{target.name} already has this content; nothing to do.",
                    fg=typer.colors.YELLOW,
                )
            skipped.append(target.name)

    return TargetReport(
        processed=tuple(processed), skipped=tuple(skipped), failed=tuple(failed)
    )


def apply_content(
    context: AssignmentContext,
    target: RepositoryTarget,
    clone_url: str,
    content: ContentPlan,
    branch: str,
    title: str,
    force_push: bool,
) -> tuple[ContentChange, ...] | None:
    """Write the content of a plan into one repository and push it as a branch.

    The branch is cut from the repository's **own** default branch, so the pull
    request contains exactly these files and nothing the student has since
    changed elsewhere. When the branch already exists, it is continued instead:
    a rerun then commits only what changed and pushes a fast-forward.
    ``force_push`` starts the branch over from the default branch. Returns the
    files written, or ``None`` when the repository already holds this content.
    """
    settings = context.settings
    with tempfile.TemporaryDirectory(prefix="ghtt-") as directory:
        workspace = Path(directory) / target.name
        start = settings.config.default_branch
        if not force_push and remote_branch_exists(
            clone_url, branch, Path(directory), settings.transport, settings.git_token
        ):
            start = branch
        clone_remote_branch(
            clone_url,
            start,
            workspace,
            settings.transport,
            settings.git_token,
        )

        changes = write_content(content, workspace, target, clone_url)
        typer.secho(f"Applying the content to {target.name}", fg=typer.colors.GREEN)
        for change in changes:
            # A replaced file may be one the student edited, so it is always
            # named rather than folded into a count.
            typer.secho(
                f"  {change.describe()}",
                fg=typer.colors.YELLOW if change.replaced else typer.colors.GREEN,
            )

        if settings.dry_run:
            typer.echo(
                f"would commit and open a pull request '{title}' on {target.name}"
            )
            return changes

        # An identical hand-out leaves nothing to commit. Pushing an empty
        # branch would only produce a pull request GitHub refuses to open.
        if not commit_all(workspace, title):
            return None

        typer.secho(f"Pushing content to {target.name}:{branch}", fg=typer.colors.GREEN)
        push_branch(
            workspace,
            clone_url,
            "HEAD",
            branch,
            settings.transport,
            settings.git_token,
            force=force_push,
        )
    return changes


class PullRequestOutcome(Enum):
    """What happened to the pull request of one repository."""

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


def open_pull_request(
    repository: Repository,
    target: RepositoryTarget,
    branch: str,
    title: str,
    body: str,
    base_branch: str,
    may_create: bool = True,
    dry_run: bool = False,
) -> PullRequestOutcome:
    """Open a pull request, or bring the open one for this branch up to date.

    GitHub allows one open pull request per branch pair, so the branch is what
    identifies it. Pushing to that branch already updates its commits; its title
    and description are edited when they differ from the requested ones.
    """
    existing = next(
        (
            pull
            for pull in repository.get_pulls(state="open", base=base_branch)
            if pull.head.ref == branch
        ),
        None,
    )

    if existing is None:
        if not may_create:
            return PullRequestOutcome.UNCHANGED
        pull_request = repository.create_pull(
            title=title, body=body, base=base_branch, head=branch
        )
        typer.secho(
            f"Created pull request {pull_request.html_url} for {target.name}",
            fg=typer.colors.GREEN,
        )
        return PullRequestOutcome.CREATED

    if existing.title == title and (existing.body or "") == body:
        typer.secho(
            f"Skipping up-to-date pull request '{title}' ({existing.html_url})",
            fg=typer.colors.GREEN,
        )
        return PullRequestOutcome.UNCHANGED
    if dry_run:
        typer.echo(f"would update pull request '{title}' ({existing.html_url})")
        return PullRequestOutcome.UNCHANGED
    typer.secho(
        f"Updating pull request '{title}' ({existing.html_url})",
        fg=typer.colors.GREEN,
    )
    existing.edit(title=title, body=body)
    return PullRequestOutcome.UPDATED
