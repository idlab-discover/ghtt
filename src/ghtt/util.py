"""Local file and Git utilities that never contact GitHub."""

from __future__ import annotations

import shutil
from pathlib import Path

import typer

from .defaults import EXPANDED_DIRECTORY_SUFFIX
from .errors import GhttError
from .git import (
    GitError,
    checkout_commit,
    clone_branch,
    commit_before,
    list_local_branches,
    require_git_repository,
)
from .report import TargetReport


class UtilityError(GhttError):
    """A local utility cannot safely complete the requested operation."""


# ==============================================================================
# grep-in
# ==============================================================================


def grep_in(path: Path, strings: str, include_header: bool) -> None:
    """Print the lines of a file that contain any of the comma-separated strings."""
    wanted = tuple(part for part in strings.split(",") if part)
    if not wanted:
        raise UtilityError("STRINGS must contain at least one search string.")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as error:
        raise UtilityError(f"File not found: {path}") from error
    except IsADirectoryError as error:
        raise UtilityError(f"Not a file: {path}") from error
    except (OSError, UnicodeDecodeError) as error:
        raise UtilityError(f"Cannot read {path}: {error}") from error

    if not lines:
        raise UtilityError(f"File is empty: {path}")

    # The first line of these exports is a CSV header. It is printed by default
    # because a matching line is only readable next to its column names.
    if include_header:
        typer.echo(lines[0].strip())

    for line in lines[1:]:
        if any(string in line for string in wanted):
            typer.echo(line.strip())


# ==============================================================================
# branches-to-folders
# ==============================================================================


def branches_to_folders(
    source: Path,
    at: str | None,
    remove_repository: bool,
    dry_run: bool,
) -> TargetReport:
    """Clone every local branch of a repository into its own sibling directory."""
    source = source.resolve()
    require_git_repository(source)

    destination_root = source.with_name(source.name + EXPANDED_DIRECTORY_SUFFIX)
    # Refusing an existing destination is what keeps this command from ever
    # deleting or overwriting work a previous run or a person put there.
    if destination_root.exists():
        raise UtilityError(
            f"The path {destination_root} already exists. Remove or rename that "
            "directory first; ghtt never deletes it for you."
        )

    branches = list_local_branches(source)
    if not branches:
        raise UtilityError(f"{source} has no local branches to expand.")

    typer.secho(
        f"# Expanding {len(branches)} branches of {source} into {destination_root}",
        fg=typer.colors.GREEN,
    )
    if dry_run:
        for branch in branches:
            typer.echo(f"would clone branch {branch} into {destination_root / branch}")
        return TargetReport(skipped=branches)

    destination_root.mkdir()

    processed: list[str] = []
    failed: list[str] = []
    for branch in branches:
        destination = destination_root / branch
        typer.secho(f"Expanding branch {branch}", fg=typer.colors.GREEN)
        try:
            clone_branch(source, branch, destination)
            if at:
                checkout_commit(destination, commit_before(destination, branch, at))
            if remove_repository:
                shutil.rmtree(destination / ".git")
        except GitError as error:
            # A branch whose worktree cannot be written is reported and left
            # behind: removing the partial clone could destroy user files.
            typer.secho(
                f"Warning: could not expand branch {branch}: {error}\n"
                f"Inspect {destination} and remove it yourself if it is unwanted.",
                fg=typer.colors.YELLOW,
                err=True,
            )
            failed.append(branch)
            continue
        except OSError as error:
            typer.secho(
                f"Warning: could not finish branch {branch}: {error}",
                fg=typer.colors.YELLOW,
                err=True,
            )
            failed.append(branch)
            continue
        processed.append(branch)

    return TargetReport(processed=tuple(processed), failed=tuple(failed))
