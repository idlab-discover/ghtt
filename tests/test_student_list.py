"""CSV validation and target plans are deterministic before any API work starts."""

from __future__ import annotations

from pathlib import Path

import pytest

from ghtt.config import Config, FieldMapping, RepositoryConfig, StudentListConfig
from ghtt.student_list import (
    Person,
    StudentListError,
    build_targets,
    load_student_list,
    normalize_group,
    parse_filter,
)


def test_normalize_group_replaces_non_alphanumeric_runs() -> None:
    assert normalize_group(" Project / Team 1! ") == "project-team-1"


def test_load_student_list_strips_one_legacy_username_marker_and_renders_comments(
    tmp_path: Path,
) -> None:
    student_list_path = tmp_path / "students.csv"
    student_list_path.write_text(
        'Username,Name,Groups\n#ada,Ada,"Team 1, Team 2"\n',
        encoding="utf-8",
    )
    student_list = StudentListConfig(
        source=student_list_path,
        field_mapping=FieldMapping(
            username="Username", comment="{{ record['Name'] }}", groups="Groups"
        ),
    )

    people = load_student_list(student_list, role="student")

    assert people[0].username == "ada"
    assert people[0].comment == "Ada"
    assert people[0].groups == ("team-1", "team-2")


def test_load_student_list_rejects_missing_configured_column(tmp_path: Path) -> None:
    student_list_path = tmp_path / "students.csv"
    student_list_path.write_text("Username\nada\n", encoding="utf-8")
    student_list = StudentListConfig(
        source=student_list_path,
        field_mapping=FieldMapping(username="GitHub username"),
    )

    with pytest.raises(StudentListError, match="missing configured column"):
        load_student_list(student_list, role="student")


def test_load_student_list_rejects_malformed_rows(tmp_path: Path) -> None:
    student_list_path = tmp_path / "students.csv"
    student_list_path.write_text("Username,Name\nada,Ada,extra\n", encoding="utf-8")
    student_list = StudentListConfig(
        source=student_list_path,
        field_mapping=FieldMapping(username="Username"),
    )

    with pytest.raises(StudentListError, match="Malformed row 2"):
        load_student_list(student_list, role="student")


def test_group_targets_include_every_multi_group_student_and_mentor() -> None:
    config = Config(
        students=StudentListConfig(
            source=Path("students.csv"),
            field_mapping=FieldMapping(username="Username", groups="Groups"),
        ),
        repos=RepositoryConfig(name_template="course-{student_group}"),
    )
    students = (
        _person("ada", groups=("team-1", "team-2")),
        _person("bert", groups=("team-1",)),
    )
    mentors = (_person("mentor", groups=("team-2",)),)

    targets = build_targets(
        config,
        organization="course",
        students=students,
        mentors=mentors,
    )

    assert [
        (target.name, [person.username for person in target.students])
        for target in targets
    ] == [
        ("course-team-1", ["ada", "bert"]),
        ("course-team-2", ["ada"]),
    ]
    assert [person.username for person in targets[1].mentors] == ["mentor"]


def test_filters_are_intersected_after_group_repositories_are_complete() -> None:
    config = _group_config()
    students = (
        _person("ada", groups=("team-1",)),
        _person("bert", groups=("team-1",)),
        _person("cy", groups=("team-2",)),
    )

    targets = build_targets(
        config,
        organization="course",
        students=students,
        student_filter=parse_filter("ada", option="--students"),
        group_filter=parse_filter("Team 1", option="--groups"),
    )

    assert len(targets) == 1
    assert [person.username for person in targets[0].students] == ["ada", "bert"]


def test_repo_template_rejects_unknown_placeholders() -> None:
    with pytest.raises(StudentListError, match="Unknown repository name placeholder"):
        build_targets(
            Config(repos=RepositoryConfig(name_template="{unknown}")),
            organization="course",
            students=(_person("ada"),),
        )


def test_repo_template_rejects_duplicate_individual_names() -> None:
    with pytest.raises(StudentListError, match="duplicate names"):
        build_targets(
            Config(repos=RepositoryConfig(name_template="course")),
            organization="course",
            students=(_person("ada"), _person("bert")),
        )


def test_parse_filter_rejects_empty_input() -> None:
    with pytest.raises(StudentListError, match="--students must contain"):
        parse_filter(" , ", option="--students")


def _group_config() -> Config:
    return Config(
        students=StudentListConfig(
            source=Path("students.csv"),
            field_mapping=FieldMapping(username="Username", group="Group"),
        )
    )


def _person(username: str, *, groups: tuple[str, ...] = ()) -> Person:
    return Person(username=username, comment=username.title(), groups=groups, record={})
