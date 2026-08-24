"""Push updated assignment code to student repositories and open pull requests."""

from __future__ import annotations

import tempfile
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
    and it needs no access to the source repository or its history.
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
        try:
            if not content.is_empty:
                changed = apply_content(
                    context, target, clone_url, content, branch, title, force_push
                )
                if changed is None:
                    typer.secho(
                        f"{target.name} already has this content; nothing to do.",
                        fg=typer.colors.YELLOW,
                    )
                    skipped.append(target.name)
                    continue
                if settings.dry_run:
                    skipped.append(target.name)
                    continue
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
                "--force-push to overwrite it.",
                fg=typer.colors.YELLOW,
                err=True,
            )
            failed.append(f"{target.name}: push was rejected")
            continue

        try:
            opened = open_pull_request(
                repository, target, branch, title, body, default_branch
            )
        except GithubException as error:
            explained = explain_github_error(
                error, "create a pull request on", target.name
            )
            typer.secho(f"Warning: {explained}", fg=typer.colors.YELLOW, err=True)
            failed.append(f"{target.name}: {explained}")
            continue

        # Pushing to the branch of an existing pull request updates that pull
        # request, so the target was still acted on even though no new one was
        # opened. Only a run that did neither has nothing to report.
        if opened or source is not None or not content.is_empty:
            processed.append(target.name)
        else:
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
    changed elsewhere. Returns the files written, or ``None`` when the
    repository already holds this content.
    """
    settings = context.settings
    with tempfile.TemporaryDirectory(prefix="ghtt-") as directory:
        workspace = Path(directory) / target.name
        clone_remote_branch(
            clone_url,
            settings.config.default_branch,
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


def open_pull_request(
    repository: Repository,
    target: RepositoryTarget,
    branch: str,
    title: str,
    body: str,
    base_branch: str,
) -> bool:
    """Open a pull request unless an open one already covers this branch pair.

    Returns whether a new pull request was created. Pushing to the branch of an
    existing pull request already updates it, so opening a second one would only
    split the same review in two.
    """
    for existing in repository.get_pulls(state="open", base=base_branch):
        if existing.head.ref == branch:
            typer.secho(
                f"Pull request {existing.html_url} already exists for "
                f"{branch} -> {base_branch}; it was updated by the push.",
                fg=typer.colors.YELLOW,
            )
            return False

    pull_request = repository.create_pull(
        title=title, body=body, base=base_branch, head=branch
    )
    typer.secho(
        f"Created pull request {pull_request.html_url} for {target.name}",
        fg=typer.colors.GREEN,
    )
    return True
