"""Give students access to their repository and take it away again."""

from __future__ import annotations

import typer
from github import GithubException

from .assignment import AssignmentContext
from .defaults import CollaboratorPermission
from .github import explain_github_error
from .prompt import Confirmer
from .report import TargetReport

# ==============================================================================
# grant
# ==============================================================================


def grant_access(
    context: AssignmentContext, read_only: bool, assume_yes: bool
) -> TargetReport:
    """Add each student as a collaborator on the repository selected for them."""
    permission = (
        CollaboratorPermission.PULL if read_only else CollaboratorPermission.PUSH
    )
    dry_run = context.settings.dry_run
    confirmer = Confirmer(f"give students {permission} access to", assume_yes, dry_run)

    processed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    for target in context.targets:
        repository = context.existing(target)
        if repository is None:
            typer.secho(
                f"Warning: repository {target.name} does not exist; skipping. "
                "Create it first with `ghtt assignment create-repos`.",
                fg=typer.colors.YELLOW,
                err=True,
            )
            failed.append(f"{target.name}: repository does not exist")
            continue

        usernames = [student.username for student in target.students]
        if not confirmer.should_proceed(
            f'{", ".join(usernames)}" {permission} access to "{target.url}'
        ):
            skipped.append(target.name)
            continue

        typer.secho(
            f"Granting {', '.join(usernames)} {permission} access to {target.name}",
            fg=typer.colors.GREEN,
        )
        target_failed = False
        for student in target.students:
            if dry_run:
                typer.echo(
                    f"would grant {student.username} {permission} access "
                    f"to {target.name}"
                )
                continue
            try:
                repository.add_to_collaborators(student.username, permission.value)
            except GithubException as error:
                # A student who mistyped their username, or who never made an
                # account, must not stop the rest of the class from being set up.
                if error.status == 404:
                    typer.secho(
                        f"Warning: {student.username} ({student.comment}) has no "
                        "GitHub account or cannot be invited; skipping.",
                        fg=typer.colors.YELLOW,
                        err=True,
                    )
                    continue
                explained = explain_github_error(
                    error,
                    "grant access to",
                    f"{target.name} for {student.username}",
                )
                typer.secho(f"Warning: {explained}", fg=typer.colors.YELLOW, err=True)
                target_failed = True

        if target_failed:
            failed.append(f"{target.name}: one or more students could not be granted")
        else:
            processed.append(target.name)

    return TargetReport(
        processed=tuple(processed), skipped=tuple(skipped), failed=tuple(failed)
    )


# ==============================================================================
# remove-grant
# ==============================================================================


def remove_access(context: AssignmentContext, assume_yes: bool) -> TargetReport:
    """Cancel pending invitations and then remove students as collaborators."""
    dry_run = context.settings.dry_run
    confirmer = Confirmer("remove grants from", assume_yes, dry_run)

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

        usernames = {student.username for student in target.students}
        try:
            # Invitations go first. Removing the collaborator first would leave a
            # window in which a student accepts the invitation and keeps access.
            for invitation in repository.get_pending_invitations():
                invitee = invitation.invitee.login if invitation.invitee else ""
                if invitee not in usernames:
                    continue
                if dry_run:
                    typer.echo(
                        f"would cancel the invitation for {invitee} on {target.name}"
                    )
                    continue
                typer.secho(
                    f"Cancelling invitation for {invitee} on {target.name}",
                    fg=typer.colors.GREEN,
                )
                repository.remove_invitation(invitation.id)

            for username in sorted(usernames):
                if dry_run:
                    typer.echo(f"would remove {username} from {target.name}")
                    continue
                typer.secho(
                    f"Removing {username} as collaborator from {target.name}",
                    fg=typer.colors.GREEN,
                )
                try:
                    repository.remove_from_collaborators(username)
                except GithubException as error:
                    # Removing someone who is already gone is the desired end
                    # state, so it is reported as success rather than an error.
                    if error.status != 404:
                        raise
                    typer.secho(
                        f"{username} was already not a collaborator on {target.name}",
                        fg=typer.colors.YELLOW,
                    )
        except GithubException as error:
            explained = explain_github_error(error, "remove access to", target.name)
            typer.secho(f"Warning: {explained}", fg=typer.colors.YELLOW, err=True)
            failed.append(f"{target.name}: access could not be removed")
            continue

        processed.append(target.name)

    return TargetReport(
        processed=tuple(processed), skipped=tuple(skipped), failed=tuple(failed)
    )
