"""Destructive commands keep both safeguards and always confirm per repository."""

from __future__ import annotations

from typing import Any

import pytest
import typer

from ghtt.config import Config
from ghtt.prompt import Aborted
from ghtt.repositories import (
    DeletionNotEnabled,
    RenameError,
    delete_repositories,
    rename_repositories,
    require_deletion_enabled,
)

from .factories import make_context, make_settings, make_target
from .fake_github import FakeGithub, FakeOrganization, FakeRepository

# ==============================================================================
# delete-repos safeguards
# ==============================================================================


def test_deletion_requires_destroy_data() -> None:
    settings = make_settings(Config(enable_repo_delete=True))

    with pytest.raises(DeletionNotEnabled, match="--destroy-data"):
        require_deletion_enabled(settings, destroy_data=False)


def test_deletion_requires_the_project_opt_in() -> None:
    settings = make_settings(Config(enable_repo_delete=False))

    with pytest.raises(DeletionNotEnabled, match="enable-repo-delete"):
        require_deletion_enabled(settings, destroy_data=True)


def test_deletion_with_both_opt_ins_is_allowed() -> None:
    require_deletion_enabled(make_settings(Config(enable_repo_delete=True)), True)


# ==============================================================================
# delete-repos
# ==============================================================================


def answer(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> list[str]:
    """Answer each confirmation prompt in turn and record the questions asked."""
    asked: list[str] = []

    def fake_prompt(text: str, value_proc: Any = None, **_: Any) -> Any:
        asked.append(text)
        reply = answers.pop(0)
        return value_proc(reply) if value_proc else reply

    monkeypatch.setattr(typer, "prompt", fake_prompt)
    return asked


def test_delete_repos_asks_about_every_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories = (FakeRepository("course-team-1"), FakeRepository("course-team-2"))
    targets = (make_target("course-team-1"), make_target("course-team-2"))
    context = make_context(targets, repositories)
    asked = answer(monkeypatch, ["y", "n"])

    report = delete_repositories(context)

    assert len(asked) == 2
    assert repositories[0].deleted is True
    assert repositories[1].deleted is False
    assert report.processed == ("course-team-1",)
    assert report.skipped == ("course-team-2",)


def test_delete_repos_never_offers_an_answer_for_all_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--yes` and `all` must not exist here: a wrong answer destroys a course."""
    asked = answer(monkeypatch, ["n"])
    context = make_context(
        (make_target("course-team-1"),), (FakeRepository("course-team-1"),)
    )

    delete_repositories(context)

    assert asked == [
        "Do you want to permanently delete the repository and all its data at "
        '"https://github.example.edu/course/course-team-1"? (y, n, abort)'
    ]


def test_delete_repos_stops_the_whole_run_on_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories = (FakeRepository("course-team-1"), FakeRepository("course-team-2"))
    targets = (make_target("course-team-1"), make_target("course-team-2"))
    answer(monkeypatch, ["abort"])

    with pytest.raises(Aborted):
        delete_repositories(make_context(targets, repositories))

    assert [repository.deleted for repository in repositories] == [False, False]


def test_delete_repos_skips_a_repository_that_is_already_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer(monkeypatch, [])
    context = make_context((make_target("course-team-1"),), ())

    report = delete_repositories(context)

    assert report.skipped == ("course-team-1",)
    assert report.failed == ()


def test_delete_repos_dry_run_deletes_nothing_and_asks_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository("course-team-1")
    answer(monkeypatch, [])
    context = make_context(
        (make_target("course-team-1"),),
        (repository,),
        settings=make_settings(dry_run=True),
    )

    report = delete_repositories(context)

    assert repository.deleted is False
    assert report.skipped == ("course-team-1",)


# ==============================================================================
# rename-repo
# ==============================================================================


def rename_client(names: tuple[str, ...]) -> FakeGithub:
    organization = FakeOrganization(
        "course", [FakeRepository(name, organization="course") for name in names]
    )
    return FakeGithub(organization=organization)


def run_rename(
    monkeypatch: pytest.MonkeyPatch,
    names: tuple[str, ...],
    match: str,
    replace: str,
    dry_run: bool = False,
) -> tuple[FakeGithub, Any]:
    client = rename_client(names)
    monkeypatch.setattr("ghtt.repositories.connect_github", lambda *_: client)
    report = rename_repositories(
        make_settings(dry_run=dry_run), match, replace, assume_yes=True
    )
    return client, report


def test_rename_applies_the_replacement_to_matching_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, report = run_rename(
        monkeypatch,
        ("studnt-ada", "studnt-bert", "teacher-notes"),
        "studnt-(.*)",
        r"student-\1",
    )

    assert client.organization is not None
    assert sorted(r.name for r in client.organization.repositories) == [
        "student-ada",
        "student-bert",
        "teacher-notes",
    ]
    assert report.processed == (
        "studnt-ada -> student-ada",
        "studnt-bert -> student-bert",
    )


def test_rename_announces_every_repository_as_it_goes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Answering `all` must not leave a long run looking like it has hung."""
    run_rename(
        monkeypatch,
        ("studnt-ada", "studnt-bert", "studnt-cy"),
        "studnt-(.*)",
        r"student-\1",
    )

    printed = capsys.readouterr().out
    for name in ("studnt-ada", "studnt-bert", "studnt-cy"):
        assert f"Renaming {name} to student-" in printed
    assert "Listing the repositories of course" in printed


def test_rename_operates_on_the_whole_organization_not_the_student_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, report = run_rename(
        monkeypatch, ("old-exam-2024",), "old-(.*)", r"archive-\1"
    )

    assert report.processed == ("old-exam-2024 -> archive-exam-2024",)
    assert client.organization is not None
    assert client.organization.listings == 1


def test_rename_refuses_a_name_that_is_already_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, report = run_rename(
        monkeypatch, ("studnt-ada", "student-ada"), "studnt-(.*)", r"student-\1"
    )

    assert report.processed == ()
    assert "already exists" in report.failed[0]
    assert client.organization is not None
    assert sorted(r.name for r in client.organization.repositories) == [
        "student-ada",
        "studnt-ada",
    ]


def test_rename_reports_an_invalid_regular_expression() -> None:
    with pytest.raises(RenameError, match="Invalid --match"):
        rename_repositories(make_settings(), "studnt-(", "student", assume_yes=True)


def test_rename_reports_an_invalid_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    client = rename_client(("studnt-ada",))
    monkeypatch.setattr("ghtt.repositories.connect_github", lambda *_: client)

    with pytest.raises(RenameError, match="Invalid --replace"):
        rename_repositories(
            make_settings(), "studnt-(.*)", r"student-\9", assume_yes=True
        )


def test_rename_dry_run_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    client, report = run_rename(
        monkeypatch, ("studnt-ada",), "studnt-(.*)", r"student-\1", dry_run=True
    )

    assert client.organization is not None
    assert [r.name for r in client.organization.repositories] == ["studnt-ada"]
    assert report.skipped == ("studnt-ada",)


def test_rename_without_a_match_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _, report = run_rename(
        monkeypatch, ("teacher-notes",), "studnt-(.*)", r"student-\1"
    )

    assert report.processed == ()
    assert report.skipped == ()
    assert report.failed == ()
