"""The example project shipped with ghtt keeps working exactly as documented.

These tests read the real files under docs/examples/project-config/, so a change
that would break an existing course project fails here first.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from github import Github
from typer.testing import CliRunner

from ghtt.cli import app
from ghtt.config import config_schema, load_config
from ghtt.issues import IssueSpec, MilestoneSpec, parse_entries
from ghtt.student_list import build_targets, load_student_list

from .fake_github import FakeGithub, FakeOrganization, FakeRepository

EXAMPLE = Path(__file__).parent.parent / "docs" / "examples" / "project-config"
runner = CliRunner()


def load_example():
    return load_config(EXAMPLE / "ghtt.yaml", EXAMPLE)


# ==============================================================================
# The example project
# ==============================================================================


def test_the_example_config_and_student_list_produce_the_documented_plan() -> None:
    config = load_example()
    assert config.students is not None

    students = load_student_list(config.students, role="student")
    targets = build_targets(
        config,
        organization="ghtt-test",
        students=students,
        github_url="https://github.ugent.be",
    )

    assert [
        (target.name, target.group, [student.username for student in target.students])
        for target in targets
    ] == [
        ("my_custom_text-group-1", "group-1", ["jfmoeyer", "mesebrec"]),
        ("my_custom_text-group-2", "group-2", ["bvolckae", "togoetha"]),
    ]
    # The leading '#' of a legacy export is stripped, and the comment template
    # produces the repository description.
    assert targets[0].description == "Jerico Moeyersons, Merlijn Sebrechts"
    assert targets[0].url == "https://github.ugent.be/ghtt-test/my_custom_text-group-1"


def test_the_example_config_supplies_the_instance_and_organization() -> None:
    config = load_example()

    assert config.url == "https://github.ugent.be/ghtt-test"
    assert config.source == EXAMPLE / "template"
    assert config.expected_group_size == 2
    assert config.repos.has_issues is True


def test_the_example_issue_template_is_accepted() -> None:
    rendered = (EXAMPLE / "lab1-assignment.yaml").read_text(encoding="utf-8")

    entries = parse_entries(rendered, EXAMPLE / "lab1-assignment.yaml", "team")

    assert isinstance(entries[0], MilestoneSpec)
    assert entries[0].title == "Deadline lab 1"
    assert entries[0].due_date is not None
    assert isinstance(entries[1], IssueSpec)
    assert entries[1].milestone == "Deadline lab 1"
    assert entries[1].assignees == ("mesebrec",)


def test_the_schema_still_names_every_legacy_key() -> None:
    schema = config_schema()
    repos = schema["$defs"]["RepositoryConfig"]["properties"]
    students = schema["$defs"]["StudentListConfig"]["properties"]
    mapping = schema["$defs"]["FieldMapping"]["properties"]

    assert {"url", "source", "default-branch", "enable-repo-delete"} <= set(
        schema["properties"]
    )
    assert {"expected-group-size", "expected-mentors-per-group"} <= set(
        schema["properties"]
    )
    assert {"name-template", "has-issues", "has-wiki", "require-pull-requests"} <= set(
        repos
    )
    assert "field-mapping" in students
    assert {"username", "comment", "group", "groups"} <= set(mapping)


# ==============================================================================
# Legacy command invocations
# ==============================================================================


def test_the_legacy_call_style_still_selects_the_example_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ghtt assignment --token X grant` keeps working, config file and all."""
    organization = FakeOrganization(
        "ghtt-test",
        [
            FakeRepository("my_custom_text-group-1", organization="ghtt-test"),
            FakeRepository("my_custom_text-group-2", organization="ghtt-test"),
        ],
    )
    client = FakeGithub(organization=organization)
    monkeypatch.setattr(
        "ghtt.assignment.connect_github", lambda *_: cast(Github, client)
    )

    result = runner.invoke(
        app,
        [
            "assignment",
            "--config",
            str(EXAMPLE / "ghtt.yaml"),
            "--token",
            "test-token",
            "--dry-run",
            "grant",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "my_custom_text-group-1" in result.output
    assert "would grant mesebrec push access" in result.output
    # A dry run reaches GitHub only to read, and only once.
    assert organization.listings == 1
    assert all(
        repository.request_count == 0 for repository in organization.repositories
    )


def test_the_filters_narrow_the_example_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = FakeOrganization(
        "ghtt-test",
        [FakeRepository("my_custom_text-group-1", organization="ghtt-test")],
    )
    monkeypatch.setattr(
        "ghtt.assignment.connect_github",
        lambda *_: cast(Github, FakeGithub(organization=organization)),
    )

    result = runner.invoke(
        app,
        [
            "assignment",
            "--config",
            str(EXAMPLE / "ghtt.yaml"),
            "--token",
            "test-token",
            "--dry-run",
            "grant",
            "--groups",
            "Group 1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "my_custom_text-group-1" in result.output
    assert "my_custom_text-group-2" not in result.output
    # Selecting the group keeps both of its members.
    assert "mesebrec" in result.output
    assert "jfmoeyer" in result.output


def test_an_empty_selection_is_an_error_rather_than_a_silent_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ghtt.assignment.connect_github",
        lambda *_: cast(Github, FakeGithub(organization=FakeOrganization("ghtt-test"))),
    )

    result = runner.invoke(
        app,
        [
            "assignment",
            "--config",
            str(EXAMPLE / "ghtt.yaml"),
            "--token",
            "test-token",
            "grant",
            "--students",
            "nobody",
        ],
    )

    assert result.exit_code == 1
    assert "No repositories match" in result.output
