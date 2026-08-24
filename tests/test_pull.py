"""pull fetches into local branches without disturbing the caller's worktree."""

from __future__ import annotations

from pathlib import Path

import pytest

from ghtt.config import Config
from ghtt.errors import GhttError
from ghtt.pull import pull_repositories

from .factories import make_context, make_settings, make_target
from .fake_github import FakeRepository
from .local_git import branches_of, git, make_bare_repository, make_repository


def student_repository(tmp_path: Path, name: str, message: str) -> FakeRepository:
    """Create a bare repository with one student commit, exposed as a fake repo."""
    bare = make_bare_repository(tmp_path / f"{name}.git")
    work = make_repository(tmp_path / f"{name}-work")
    (work / "solution.py").write_text("print('hi')\n", encoding="utf-8")
    git(work, "add", "-A")
    git(
        work,
        "-c",
        "user.email=ada@example.edu",
        "-c",
        "user.name=Ada",
        "commit",
        "-m",
        message,
    )
    git(work, "push", str(bare), "master:master")

    repository = FakeRepository(name)
    repository.clone_url = str(bare)
    repository.ssh_url = str(bare)
    repository.description = "Ada Lovelace"
    return repository


def test_pull_fetches_each_repository_into_its_own_branch(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template")
    repository = student_repository(tmp_path, "course-ada", "solve the exercise")
    context = make_context(
        (make_target("course-ada", students=("ada",)),),
        (repository,),
        settings=make_settings(Config(source=source, default_branch="master")),
    )

    report = pull_repositories(context, force=False, assume_yes=True)

    assert "course-ada" in branches_of(source)
    assert report.processed == ("course-ada",)


def test_pull_leaves_the_checked_out_branch_alone(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template")
    repository = student_repository(tmp_path, "course-ada", "solve the exercise")
    context = make_context(
        (make_target("course-ada", students=("ada",)),),
        (repository,),
        settings=make_settings(Config(source=source, default_branch="master")),
    )

    pull_repositories(context, force=False, assume_yes=True)

    assert git(source, "rev-parse", "--abbrev-ref", "HEAD").strip() == "master"
    assert not (source / "solution.py").exists()


def test_a_missing_repository_becomes_a_failed_row_not_a_stopped_run(
    tmp_path: Path,
) -> None:
    source = make_repository(tmp_path / "template")
    present = student_repository(tmp_path, "course-ada", "solve the exercise")
    context = make_context(
        (
            make_target("course-absent", students=("bert",)),
            make_target("course-ada", students=("ada",)),
        ),
        (present,),
        settings=make_settings(Config(source=source, default_branch="master")),
    )

    report = pull_repositories(context, force=False, assume_yes=True)

    assert report.processed == ("course-ada",)
    assert "course-absent" in report.failed[0]
    assert "course-ada" in branches_of(source)


def test_a_diverged_local_branch_fails_until_force_is_given(tmp_path: Path) -> None:
    # The local branch already carries a commit the student repository lacks,
    # so accepting the fetch would silently throw that local work away.
    source = make_repository(tmp_path / "template", branches=("course-ada",))
    repository = student_repository(tmp_path, "course-ada", "solve the exercise")
    context = make_context(
        (make_target("course-ada", students=("ada",)),),
        (repository,),
        settings=make_settings(Config(source=source, default_branch="master")),
    )

    rejected = pull_repositories(context, force=False, assume_yes=True)
    forced = pull_repositories(context, force=True, assume_yes=True)

    assert rejected.failed == ("course-ada: fetch failed",)
    assert forced.processed == ("course-ada",)


def test_pull_requires_a_source_repository() -> None:
    context = make_context((make_target("course-ada", students=("ada",)),), ())

    with pytest.raises(GhttError, match="Missing source repository"):
        pull_repositories(context, force=False, assume_yes=True)


def test_dry_run_fetches_nothing(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template")
    repository = student_repository(tmp_path, "course-ada", "solve the exercise")
    context = make_context(
        (make_target("course-ada", students=("ada",)),),
        (repository,),
        settings=make_settings(
            Config(source=source, default_branch="master"), dry_run=True
        ),
    )

    report = pull_repositories(context, force=False, assume_yes=False)

    assert branches_of(source) == ["master"]
    assert report.skipped == ("course-ada",)
