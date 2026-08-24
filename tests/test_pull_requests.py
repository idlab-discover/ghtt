"""create-pr pushes a branch per target and never duplicates an open pull request."""

from __future__ import annotations

from pathlib import Path

import pytest

from ghtt.config import Config
from ghtt.errors import GhttError
from ghtt.pull_requests import create_pull_requests
from ghtt.templates import ContentFile, ContentPlan

from .factories import make_context, make_settings, make_target
from .fake_github import FakeRepository
from .local_git import (
    branches_of,
    file_in_branch,
    git,
    make_bare_repository,
    make_repository,
)


def student_repository(tmp_path: Path, name: str) -> FakeRepository:
    """Create a bare repository that already holds the source history."""
    bare = make_bare_repository(tmp_path / f"{name}.git")
    repository = FakeRepository(name)
    repository.clone_url = str(bare)
    repository.ssh_url = str(bare)
    return repository


def seed(source: Path, repository: FakeRepository) -> None:
    git(source, "push", repository.clone_url, "master:master")


def context_for(
    source: Path, repositories: tuple[FakeRepository, ...], dry_run: bool = False
):
    targets = tuple(
        make_target(repository.name, students=("ada",)) for repository in repositories
    )
    return make_context(
        targets,
        repositories,
        settings=make_settings(
            Config(source=source, default_branch="master"), dry_run=dry_run
        ),
    )


def target_with_record(name: str, username: str, record: dict[str, str]):
    """A target whose student carries their own row from the student list."""
    target = make_target(name, students=(username,))
    return target.model_copy(
        update={"students": (target.students[0].model_copy(update={"record": record}),)}
    )


# ==============================================================================
# Shared branch mode
# ==============================================================================


def test_the_same_branch_is_pushed_to_every_repository(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template")
    repositories = tuple(
        student_repository(tmp_path, name) for name in ("course-ada", "course-bert")
    )
    for repository in repositories:
        seed(source, repository)
    context = context_for(source, repositories)

    report = create_pull_requests(
        context,
        branch="lab2",
        title="Lab 2",
        body="Here is lab 2.",
        branch_already_pushed=False,
        content=ContentPlan(),
        force_push=False,
        assume_yes=True,
    )

    for repository in repositories:
        assert repository.clone_url is not None
        assert "lab2" in branches_of(Path(repository.clone_url))
        assert [pull.head.ref for pull in repository.pulls] == ["lab2"]
        assert repository.pulls[0].base.ref == "master"
    assert report.processed == ("course-ada", "course-bert")


def test_branch_already_pushed_only_opens_the_pull_requests(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template")
    repository = student_repository(tmp_path, "course-ada")
    seed(source, repository)
    context = context_for(source, (repository,))

    create_pull_requests(
        context,
        branch="lab2",
        title="Lab 2",
        body="Here is lab 2.",
        branch_already_pushed=True,
        content=ContentPlan(),
        force_push=False,
        assume_yes=True,
    )

    assert repository.clone_url is not None
    assert branches_of(Path(repository.clone_url)) == ["master"]
    assert [pull.head.ref for pull in repository.pulls] == ["lab2"]


def test_an_open_pull_request_is_reused_instead_of_duplicated(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template")
    repository = student_repository(tmp_path, "course-ada")
    seed(source, repository)
    context = context_for(source, (repository,))
    arguments = {
        "branch": "lab2",
        "title": "Lab 2",
        "body": "Here is lab 2.",
        "branch_already_pushed": True,
        "content": ContentPlan(),
        "force_push": False,
        "assume_yes": True,
    }

    create_pull_requests(context, **arguments)
    second = create_pull_requests(context, **arguments)

    assert len(repository.pulls) == 1
    assert second.processed == ()
    assert second.skipped == ("course-ada",)


# ==============================================================================
# Content directory mode
# ==============================================================================


def content_dir_with(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a plain directory of hand-out files, which needs no Git at all."""
    root = tmp_path / "handout"
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def hand_out(
    context, content_dir: Path | None = None, branch: str = "handout", **overrides
):
    """Hand out one directory, or whatever plan an override supplies instead."""
    directories = () if content_dir is None else (str(content_dir),)
    arguments = {
        "branch": branch,
        "title": "Hand-out",
        "body": "body",
        "branch_already_pushed": False,
        "content": ContentPlan(directories=directories),
        "force_push": False,
        "assume_yes": True,
    }
    arguments.update(overrides)
    return create_pull_requests(context, **arguments)


def test_content_reaches_each_repository_rendered_for_that_student(
    tmp_path: Path,
) -> None:
    source = make_repository(tmp_path / "template")
    repositories = tuple(
        student_repository(tmp_path, name) for name in ("course-ada", "course-bert")
    )
    for repository in repositories:
        seed(source, repository)
    context = make_context(
        (
            target_with_record("course-ada", "ada", {"API key": "key-ada"}),
            target_with_record("course-bert", "bert", {"API key": "key-bert"}),
        ),
        repositories,
        settings=make_settings(Config(source=source, default_branch="master")),
    )
    content = content_dir_with(
        tmp_path, {"credentials.env.jinja": "KEY={{ students[0].record['API key'] }}\n"}
    )

    report = hand_out(context, content)

    assert report.processed == ("course-ada", "course-bert")
    ada = file_in_branch(Path(repositories[0].clone_url), "handout", "credentials.env")
    bert = file_in_branch(Path(repositories[1].clone_url), "handout", "credentials.env")
    assert ada.strip() == "KEY=key-ada"
    assert bert.strip() == "KEY=key-bert"


def test_the_pull_request_contains_only_the_handout(tmp_path: Path) -> None:
    """The whole point: a student's own work never appears in the diff."""
    source = make_repository(tmp_path / "template")
    (source / "assignment.md").write_text("Do the exercise.\n", encoding="utf-8")
    git(source, "add", "-A")
    git(source, "commit", "-m", "assignment")
    repository = student_repository(tmp_path, "course-ada")
    seed(source, repository)

    # The student edits a file that came from the template.
    work = tmp_path / "student-work"
    git(source, "clone", "--branch", "master", repository.clone_url, str(work))
    (work / "assignment.md").write_text("Do the exercise.\n\nMy answer.\n", "utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-m", "student answer")
    git(work, "push", "origin", "master")

    # Meanwhile the teacher changes the template for a later cohort.
    (source / "assignment.md").write_text("Do the exercise, carefully.\n", "utf-8")
    git(source, "add", "-A")
    git(source, "commit", "-m", "reword")

    context = make_context(
        (make_target("course-ada", students=("ada",)),),
        (repository,),
        settings=make_settings(Config(source=source, default_branch="master")),
    )
    content = content_dir_with(tmp_path, {"credentials.env": "KEY=abc\n"})

    hand_out(context, content)

    bare = Path(repository.clone_url)
    base = git(bare, "merge-base", "master", "handout").strip()
    changed = git(bare, "diff", "--name-only", f"{base}..handout").split()
    assert changed == ["credentials.env"]
    # The student's answer is untouched by the hand-out.
    assert "My answer." in file_in_branch(bare, "handout", "assignment.md")


def test_content_replaces_an_existing_file_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = make_repository(tmp_path / "template")
    (source / "docs").mkdir()
    (source / "docs" / "task.md").write_text("Old wording.\n", encoding="utf-8")
    git(source, "add", "-A")
    git(source, "commit", "-m", "docs")
    repository = student_repository(tmp_path, "course-ada")
    seed(source, repository)
    context = context_for(source, (repository,))
    content = content_dir_with(
        tmp_path,
        {"docs/task.md": "Corrected wording.\n", "NOTES.md": "New file.\n"},
    )

    hand_out(context, content)

    printed = capsys.readouterr().out
    # A replaced file is marked differently from a new one.
    assert "~ docs/task.md" in printed
    assert "+ NOTES.md" in printed
    bare = Path(repository.clone_url)
    assert file_in_branch(bare, "handout", "docs/task.md") == "Corrected wording.\n"
    assert file_in_branch(bare, "handout", "NOTES.md") == "New file.\n"


def test_a_repository_that_already_has_the_content_is_skipped(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template")
    (source / "NOTES.md").write_text("Same.\n", encoding="utf-8")
    git(source, "add", "-A")
    git(source, "commit", "-m", "notes")
    repository = student_repository(tmp_path, "course-ada")
    seed(source, repository)
    context = context_for(source, (repository,))
    content = content_dir_with(tmp_path, {"NOTES.md": "Same.\n"})

    report = hand_out(context, content)

    assert report.skipped == ("course-ada",)
    assert report.processed == ()
    # No empty branch and no pull request GitHub would refuse to open.
    assert branches_of(Path(repository.clone_url)) == ["master"]
    assert repository.pulls == []


def test_a_content_hand_out_needs_no_source_repository(tmp_path: Path) -> None:
    """A colleague without the assignment template can still hand something out."""
    source = make_repository(tmp_path / "template")
    repository = student_repository(tmp_path, "course-ada")
    seed(source, repository)
    context = make_context(
        (make_target("course-ada", students=("ada",)),),
        (repository,),
        # No `source` at all in the settings of this run.
        settings=make_settings(Config(default_branch="master")),
    )
    content = content_dir_with(tmp_path, {"NOTES.md": "Read this.\n"})

    report = hand_out(context, content)

    assert report.processed == ("course-ada",)
    assert file_in_branch(Path(repository.clone_url), "handout", "NOTES.md")


def test_a_missing_content_directory_is_an_actionable_error(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template")
    repository = student_repository(tmp_path, "course-ada")
    seed(source, repository)
    context = context_for(source, (repository,))

    with pytest.raises(GhttError, match="Content directory not found"):
        hand_out(context, tmp_path / "absent")


def test_content_cannot_claim_the_branch_is_already_pushed(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template")
    repository = student_repository(tmp_path, "course-ada")
    seed(source, repository)
    context = context_for(source, (repository,))
    content = content_dir_with(tmp_path, {"NOTES.md": "x\n"})

    with pytest.raises(GhttError, match="cannot be combined"):
        hand_out(context, content, branch_already_pushed=True)


def test_a_content_dry_run_writes_nothing(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template")
    repository = student_repository(tmp_path, "course-ada")
    seed(source, repository)
    context = make_context(
        (make_target("course-ada", students=("ada",)),),
        (repository,),
        settings=make_settings(
            Config(source=source, default_branch="master"), dry_run=True
        ),
    )
    content = content_dir_with(tmp_path, {"NOTES.md": "Read this.\n"})

    report = hand_out(context, content, assume_yes=False)

    assert report.skipped == ("course-ada",)
    assert branches_of(Path(repository.clone_url)) == ["master"]
    assert repository.pulls == []


def test_rotating_the_content_needs_force_push(tmp_path: Path) -> None:
    """Each run branches from the default branch, so a changed hand-out diverges."""
    source = make_repository(tmp_path / "template")
    repository = student_repository(tmp_path, "course-ada")
    seed(source, repository)
    context = context_for(source, (repository,))

    first = hand_out(context, content_dir_with(tmp_path, {"KEY.txt": "v1\n"}))
    rejected = hand_out(context, content_dir_with(tmp_path, {"KEY.txt": "v2\n"}))
    forced = hand_out(
        context, content_dir_with(tmp_path, {"KEY.txt": "v2\n"}), force_push=True
    )

    assert first.processed == ("course-ada",)
    assert rejected.failed == ("course-ada: push was rejected",)
    assert forced.processed == ("course-ada",)
    assert len(repository.pulls) == 1
    assert file_in_branch(Path(repository.clone_url), "handout", "KEY.txt") == "v2\n"


# ==============================================================================
# Failures
# ==============================================================================


def test_a_rejected_push_fails_only_its_own_repository(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template", branches=("lab2",))
    good = student_repository(tmp_path, "course-ada")
    conflicted = student_repository(tmp_path, "course-bert")
    seed(source, good)
    seed(source, conflicted)
    # The student repository already has a lab2 branch with other history.
    git(source, "push", conflicted.clone_url, "lab2:lab2")
    git(source, "checkout", "master")
    context = context_for(source, (good, conflicted))

    report = create_pull_requests(
        context,
        branch="lab2",
        title="Lab 2",
        body="Here is lab 2.",
        branch_already_pushed=False,
        content=ContentPlan(),
        force_push=False,
        assume_yes=True,
    )

    assert report.processed == ("course-ada",)
    assert report.failed == ("course-bert: push was rejected",)


def test_a_missing_repository_is_reported_and_the_rest_continue(
    tmp_path: Path,
) -> None:
    source = make_repository(tmp_path / "template")
    present = student_repository(tmp_path, "course-ada")
    seed(source, present)
    context = make_context(
        (
            make_target("course-absent", students=("bert",)),
            make_target("course-ada", students=("ada",)),
        ),
        (present,),
        settings=make_settings(Config(source=source, default_branch="master")),
    )

    report = create_pull_requests(
        context,
        branch="lab2",
        title="Lab 2",
        body="Here is lab 2.",
        branch_already_pushed=False,
        content=ContentPlan(),
        force_push=False,
        assume_yes=True,
    )

    assert report.processed == ("course-ada",)
    assert "course-absent" in report.failed[0]


def test_dry_run_pushes_nothing_and_opens_nothing(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template")
    repository = student_repository(tmp_path, "course-ada")
    seed(source, repository)
    context = context_for(source, (repository,), dry_run=True)

    report = create_pull_requests(
        context,
        branch="lab2",
        title="Lab 2",
        body="Here is lab 2.",
        branch_already_pushed=False,
        content=ContentPlan(),
        force_push=False,
        assume_yes=False,
    )

    assert branches_of(Path(repository.clone_url)) == ["master"]
    assert repository.pulls == []
    assert report.skipped == ("course-ada",)


# ==============================================================================
# Per-repository content
# ==============================================================================


def group_context(
    source: Path, repositories: tuple[FakeRepository, ...], groups: tuple[str, ...]
):
    """Group repositories, each expecting content of its own group."""
    targets = tuple(
        make_target(repository.name, students=("ada",), group=group)
        for repository, group in zip(repositories, groups, strict=True)
    )
    return make_context(
        targets,
        repositories,
        settings=make_settings(Config(source=source, default_branch="master")),
    )


def test_each_group_receives_only_its_own_directory(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template")
    repositories = tuple(
        student_repository(tmp_path, name)
        for name in ("course-team-1", "course-team-2")
    )
    for repository in repositories:
        seed(source, repository)
    context = group_context(source, repositories, ("team-1", "team-2"))
    for group in ("team-1", "team-2"):
        directory = tmp_path / "kubeconfigs" / group
        directory.mkdir(parents=True)
        (directory / ".kube").mkdir()
        (directory / ".kube" / "config").write_text(f"cluster: {group}\n", "utf-8")

    report = create_pull_requests(
        context,
        branch="kubeconfig",
        title="Your cluster access",
        body="Merge this to reach the cluster.",
        branch_already_pushed=False,
        content=ContentPlan(
            directories=(str(tmp_path / "kubeconfigs" / "{student_group}"),)
        ),
        force_push=False,
        assume_yes=True,
    )

    assert report.processed == ("course-team-1", "course-team-2")
    for repository, group in zip(repositories, ("team-1", "team-2"), strict=True):
        bare = Path(repository.clone_url)
        assert (
            file_in_branch(bare, "kubeconfig", ".kube/config") == f"cluster: {group}\n"
        )


def test_a_shared_directory_and_a_group_directory_are_layered(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template")
    repository = student_repository(tmp_path, "course-team-1")
    seed(source, repository)
    context = group_context(source, (repository,), ("team-1",))
    shared = tmp_path / "common"
    shared.mkdir()
    (shared / "README.md").write_text("How to use the cluster.\n", "utf-8")
    own = tmp_path / "team-1"
    own.mkdir()
    (own / "config").write_text("cluster: team-1\n", "utf-8")

    report = hand_out(
        context,
        content=ContentPlan(
            directories=(str(shared), str(tmp_path / "{student_group}"))
        ),
    )

    assert report.processed == ("course-team-1",)
    bare = Path(repository.clone_url)
    assert file_in_branch(bare, "handout", "README.md") == "How to use the cluster.\n"
    assert file_in_branch(bare, "handout", "config") == "cluster: team-1\n"


def test_a_generated_file_is_renamed_into_place(tmp_path: Path) -> None:
    """A flat directory of generated files needs no restructuring."""
    source = make_repository(tmp_path / "template")
    repository = student_repository(tmp_path, "course-team-1")
    seed(source, repository)
    context = group_context(source, (repository,), ("team-1",))
    generated = tmp_path / "kubeconfigs"
    generated.mkdir()
    (generated / "team-1.yaml").write_text("cluster: team-1\n", "utf-8")

    report = hand_out(
        context,
        content=ContentPlan(
            files=(
                ContentFile(
                    source=str(generated / "{student_group}.yaml"),
                    destination=".kube/config",
                ),
            )
        ),
    )

    assert report.processed == ("course-team-1",)
    bare = Path(repository.clone_url)
    assert file_in_branch(bare, "handout", ".kube/config") == "cluster: team-1\n"


def test_a_group_without_content_fails_alone(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template")
    repositories = tuple(
        student_repository(tmp_path, name)
        for name in ("course-team-1", "course-team-2")
    )
    for repository in repositories:
        seed(source, repository)
    context = group_context(source, repositories, ("team-1", "team-2"))
    # Only the first group has a directory; the second was never generated.
    directory = tmp_path / "kubeconfigs" / "team-1"
    directory.mkdir(parents=True)
    (directory / "config").write_text("cluster: team-1\n", "utf-8")

    report = hand_out(
        context,
        content=ContentPlan(
            directories=(str(tmp_path / "kubeconfigs" / "{student_group}"),)
        ),
    )

    assert report.processed == ("course-team-1",)
    assert len(report.failed) == 1
    assert report.failed[0].startswith("course-team-2: Content directory not found")
    # The repository that did have content is unaffected by the one that did not.
    assert file_in_branch(Path(repositories[0].clone_url), "handout", "config")
    assert branches_of(Path(repositories[1].clone_url)) == ["master"]
