"""Real local Git repositories for tests that must exercise real Git behaviour."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git(repository: Path, *arguments: str) -> str:
    """Run one Git command in a test repository and return its output."""
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def make_repository(
    path: Path, branches: tuple[str, ...] = (), default_branch: str = "master"
) -> Path:
    """Create a working repository with one commit, plus one commit per branch."""
    path.mkdir(parents=True)
    git(path, "init", "--initial-branch", default_branch)
    git(path, "config", "user.email", "teacher@example.edu")
    git(path, "config", "user.name", "Teacher")
    (path / "README.md").write_text("start\n", encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-m", "start")
    for branch in branches:
        git(path, "checkout", "-b", branch)
        (path / f"{branch}.txt").write_text(branch, encoding="utf-8")
        git(path, "add", "-A")
        git(path, "commit", "-m", f"work on {branch}")
        git(path, "checkout", default_branch)
    return path


def make_bare_repository(path: Path) -> Path:
    """Create an empty bare repository that a test can push to."""
    path.mkdir(parents=True)
    git(path, "init", "--bare", "--initial-branch", "master")
    return path


def branches_of(repository: Path) -> list[str]:
    output = git(repository, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
    return sorted(line for line in output.splitlines() if line)


def file_in_branch(repository: Path, branch: str, name: str) -> str:
    """Read one file out of a branch without checking that branch out."""
    return git(repository, "show", f"{branch}:{name}")


def commit_count(repository: Path, reference: str) -> int:
    return len(git(repository, "rev-list", reference).splitlines())
