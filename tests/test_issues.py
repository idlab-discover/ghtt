"""Issue templates are validated, rendered per repository, and applied idempotently."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ghtt.issues import (
    IssueTemplateError,
    MilestoneSpec,
    create_issues,
    due_datetime,
    parse_entries,
)

from .factories import make_context, make_settings, make_target
from .fake_github import FakeMilestone, FakeRepository

TEMPLATE = """
- type: milestone
  title: Deadline lab 1
  due date: 2026-03-09
  description: Deadline lab 1
- type: issue
  title: Assignment lab 1
  milestone: Deadline lab 1
  labels:
    - assignment
  body: |
    Clone your repository from {{ clone_url }}.
""".strip()


def write_template(tmp_path: Path, text: str = TEMPLATE) -> Path:
    path = tmp_path / "lab1-assignment.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# ==============================================================================
# Template validation
# ==============================================================================


def test_template_must_be_a_non_empty_list(tmp_path: Path) -> None:
    with pytest.raises(IssueTemplateError, match="non-empty YAML list"):
        parse_entries("title: not a list", tmp_path / "t.yaml", "course-team-1")


def test_template_rejects_an_unknown_entry_type(tmp_path: Path) -> None:
    with pytest.raises(IssueTemplateError, match="Invalid issue template"):
        parse_entries("- type: comment\n  title: hi\n", tmp_path / "t.yaml", "team")


def test_template_accepts_the_legacy_due_date_spelling(tmp_path: Path) -> None:
    entries = parse_entries(TEMPLATE, tmp_path / "t.yaml", "course-team-1")

    milestone = entries[0]
    assert isinstance(milestone, MilestoneSpec)
    assert milestone.due_date is not None


def test_a_date_only_due_date_is_local_midnight() -> None:
    due = due_datetime(datetime(2026, 3, 9).date())

    assert due is not None
    assert (due.hour, due.minute) == (0, 0)
    assert due.tzinfo is not None


# ==============================================================================
# Applying a template
# ==============================================================================


def test_milestone_and_issue_are_created_with_rendered_content(tmp_path: Path) -> None:
    repository = FakeRepository("course-team-1")
    context = make_context(
        (make_target("course-team-1", students=("ada",)),), (repository,)
    )

    report = create_issues(context, write_template(tmp_path), assume_yes=True)

    assert [milestone.title for milestone in repository.milestones] == [
        "Deadline lab 1"
    ]
    assert [issue.title for issue in repository.issues] == ["Assignment lab 1"]
    assert repository.clone_url in (repository.issues[0].body or "")
    assert report.processed == ("course-team-1",)


def test_running_twice_updates_nothing(tmp_path: Path) -> None:
    repository = FakeRepository("course-team-1")
    template = write_template(tmp_path)
    context = make_context(
        (make_target("course-team-1", students=("ada",)),), (repository,)
    )

    create_issues(context, template, assume_yes=True)
    create_issues(context, template, assume_yes=True)

    assert len(repository.milestones) == 1
    assert len(repository.issues) == 1
    assert repository.issues[0].edits == []
    assert repository.milestones[0].edits == []


def test_a_milestone_whose_due_date_moved_is_updated(tmp_path: Path) -> None:
    repository = FakeRepository("course-team-1")
    repository.milestones = [
        FakeMilestone(
            "Deadline lab 1",
            "Deadline lab 1",
            datetime(2026, 4, 1, tzinfo=UTC),
            1,
        )
    ]
    context = make_context(
        (make_target("course-team-1", students=("ada",)),), (repository,)
    )

    create_issues(context, write_template(tmp_path), assume_yes=True)

    assert len(repository.milestones[0].edits) == 1


def test_an_issue_referring_to_an_unknown_milestone_is_rejected(
    tmp_path: Path,
) -> None:
    template = write_template(
        tmp_path,
        "- type: issue\n  title: Assignment\n  milestone: Nowhere\n  body: hi\n",
    )
    repository = FakeRepository("course-team-1")
    context = make_context(
        (make_target("course-team-1", students=("ada",)),), (repository,)
    )

    with pytest.raises(IssueTemplateError, match="Nowhere"):
        create_issues(context, template, assume_yes=True)

    # Nothing was created, so the repository is not left half updated.
    assert repository.issues == []


def test_an_issue_is_still_created_when_an_assignee_cannot_be_assigned(
    tmp_path: Path,
) -> None:
    template = write_template(
        tmp_path,
        "- type: issue\n  title: Assignment\n  body: hi\n  assignees:\n"
        "    - unknown-mentor\n",
    )
    repository = FakeRepository("course-team-1")
    context = make_context(
        (make_target("course-team-1", students=("ada",)),), (repository,)
    )

    report = create_issues(context, template, assume_yes=True)

    assert [issue.title for issue in repository.issues] == ["Assignment"]
    assert repository.issues[0].assignees == []
    assert report.processed == ("course-team-1",)


def test_each_repository_costs_one_milestone_and_one_issue_listing(
    tmp_path: Path,
) -> None:
    repository = FakeRepository("course-team-1")
    context = make_context(
        (make_target("course-team-1", students=("ada",)),), (repository,)
    )

    create_issues(context, write_template(tmp_path), assume_yes=True)

    # One milestone listing, one issue listing, one create per entry.
    assert repository.request_count == 4


def test_missing_template_file_is_an_actionable_error(tmp_path: Path) -> None:
    context = make_context((make_target("course-team-1", students=("ada",)),), ())

    with pytest.raises(IssueTemplateError, match="Issue template not found"):
        create_issues(context, tmp_path / "absent.yaml", assume_yes=True)


def test_dry_run_creates_nothing(tmp_path: Path) -> None:
    repository = FakeRepository("course-team-1")
    context = make_context(
        (make_target("course-team-1", students=("ada",)),),
        (repository,),
        settings=make_settings(dry_run=True),
    )

    report = create_issues(context, write_template(tmp_path), assume_yes=False)

    assert repository.milestones == []
    assert repository.issues == []
    assert report.skipped == ("course-team-1",)
