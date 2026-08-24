"""Run local Git commands with an ephemeral HTTPS token URL when requested."""

from __future__ import annotations

import os
import subprocess
from enum import StrEnum
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from .defaults import HTTPS_TOKEN_USERNAME
from .errors import GhttError

# ==============================================================================
# Transport Choice
# ==============================================================================


class GitTransport(StrEnum):
    """The two Git transports supported by ghtt."""

    HTTPS = "https"
    SSH = "ssh"


class GitError(GhttError):
    """A Git command cannot safely complete the requested operation."""


# ==============================================================================
# Source Safety
# ==============================================================================


def require_git_repository(source: Path) -> None:
    """Reject a source directory before a command changes GitHub or local Git state."""
    # The legacy command explicitly required .git. Keep that visible safety
    # check instead of discovering a non-repository only after a repo is made.
    if not source.is_dir() or not (source / ".git").exists():
        raise GitError(
            f"Source directory {source} is not a Git repository; "
            f"expected {source / '.git'}"
        )


# ==============================================================================
# Git Execution
# ==============================================================================


def run_git(
    arguments: list[str],
    working_directory: Path,
    transport: GitTransport = GitTransport.HTTPS,
    token: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run Git with an argument list and translate failures into a user error."""
    command = ["git", *arguments]
    environment = os.environ.copy()

    # Git accepts HTTPS credentials in the remote URL. The transformed URL is
    # used only for this subprocess; callers must never use it to add a remote.
    if transport is GitTransport.HTTPS and token:
        authenticated_command: list[str] = []
        for argument in command:
            if argument.startswith("https://"):
                parsed = urlsplit(argument)
                credentials = (
                    f"{HTTPS_TOKEN_USERNAME}:{quote(token, safe='')}@{parsed.netloc}"
                )
                argument = urlunsplit(
                    (parsed.scheme, credentials, parsed.path, parsed.query, "")
                )
            authenticated_command.append(argument)
        command = authenticated_command

    # Git may otherwise open an editor or a credential prompt and hang a command
    # that is meant to run unattended over many repositories.
    environment["GIT_TERMINAL_PROMPT"] = "0"

    result = subprocess.run(
        command,
        cwd=working_directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        detail = (
            result.stderr.strip() or result.stdout.strip() or "Git returned no detail"
        )
        safe_detail = detail.replace(token, "[redacted]") if token else detail
        raise GitError(f"Git could not run {' '.join(arguments)}: {safe_detail}")
    return result


# ==============================================================================
# Repository Operations
# ==============================================================================
#
# These wrappers exist because several commands need the same Git operation with
# the same safety rules. Each one keeps its Git arguments visible so the exact
# command a user would have to reproduce by hand stays obvious.


def list_local_branches(repository: Path) -> tuple[str, ...]:
    """List the local branches of a repository in Git's own sorted order."""
    result = run_git(
        ["for-each-ref", "--format=%(refname:short)", "refs/heads/"], repository
    )
    return tuple(line for line in result.stdout.splitlines() if line)


def clone_branch(source: Path, branch: str, destination: Path) -> None:
    """Clone one branch of a local repository into a new directory."""
    run_git(
        [
            "clone",
            "--single-branch",
            "--branch",
            branch,
            str(source),
            str(destination),
        ],
        # Cloning must not depend on where the caller happened to stand, and the
        # destination does not exist yet, so run from the source repository.
        source,
    )


def clone_remote_branch(
    remote_url: str,
    branch: str,
    destination: Path,
    transport: GitTransport,
    token: str | None,
) -> None:
    """Clone one branch of a remote repository into a new directory.

    Only the requested branch is fetched, but its full history is: pushing from
    a shallow clone is not reliable, and these clones exist to be pushed.
    """
    run_git(
        ["clone", "--single-branch", "--branch", branch, remote_url, str(destination)],
        # The destination does not exist yet, so Git runs from its parent.
        destination.parent,
        transport,
        token,
    )


def commit_all(repository: Path, message: str) -> bool:
    """Commit every change in a working copy and report whether anything changed."""
    run_git(["add", "-A"], repository)
    status = run_git(["status", "--porcelain"], repository)
    if not status.stdout.strip():
        return False
    run_git(["commit", "--message", message], repository)
    return True


def push_branch(
    repository: Path,
    remote_url: str,
    local_reference: str,
    remote_branch: str,
    transport: GitTransport,
    token: str | None,
    force: bool = False,
) -> None:
    """Push one local reference to a branch of a remote that is never stored."""
    arguments = ["push"]
    if force:
        arguments.append("--force")
    arguments += [remote_url, f"{local_reference}:refs/heads/{remote_branch}"]
    run_git(arguments, repository, transport, token)


def fetch_into_branch(
    repository: Path,
    remote_url: str,
    remote_reference: str,
    local_branch: str,
    transport: GitTransport,
    token: str | None,
    force: bool = False,
) -> None:
    """Fetch a remote reference into a local branch without touching the worktree."""
    # A plain refspec refuses to rewrite history that is already stored locally.
    # Forcing is opt-in because it discards whatever the local branch held.
    refspec = f"{'+' if force else ''}{remote_reference}:refs/heads/{local_branch}"
    run_git(["fetch", remote_url, refspec], repository, transport, token)


def latest_commit(repository: Path, reference: str) -> tuple[int, str, str]:
    """Return the commit time, committer, and summary of a reference.

    One `git log` call formats all three values so that reading a summary table
    does not cost three subprocesses per repository.
    """
    separator = "\x1f"
    result = run_git(
        [
            "log",
            reference,
            "-1",
            f"--pretty=format:%ct{separator}%an <%ae>{separator}%s",
        ],
        repository,
    )
    parts = result.stdout.split(separator)
    if len(parts) != 3:
        raise GitError(f"Git returned an unreadable log entry for {reference}")
    return int(parts[0]), parts[1], parts[2]


def commit_before(repository: Path, reference: str, moment: str) -> str:
    """Find the newest first-parent commit of a reference at or before a moment."""
    result = run_git(
        ["rev-list", "-n", "1", "--first-parent", f"--before={moment}", reference],
        repository,
    )
    commit = result.stdout.strip()
    if not commit:
        raise GitError(f"{reference} has no commit at or before {moment!r}")
    return commit


def checkout_commit(repository: Path, commit: str) -> None:
    """Check out a specific commit without Git's detached-head advice."""
    run_git(["-c", "advice.detachedHead=false", "checkout", commit], repository)
