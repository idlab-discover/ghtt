"""Config defaults are optional, validated, and resolved predictably."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ghtt.__main__ import app
from ghtt.config import (
    ConfigError,
    choose_value,
    config_schema,
    load_config,
)

runner = CliRunner()


def test_command_line_value_overrides_config_and_built_in() -> None:
    assert choose_value("cli", "config", "built-in") == "cli"


def test_config_value_overrides_built_in() -> None:
    assert choose_value(None, "config", "built-in") == "config"


def test_built_in_value_is_used_when_no_other_source_exists() -> None:
    assert choose_value(None, None, "built-in") == "built-in"


def test_missing_implicit_config_is_valid(tmp_path: Path) -> None:
    config = load_config(None, current_directory=tmp_path)

    assert config.url is None
    assert config.default_branch == "master"


def test_missing_explicit_config_is_an_actionable_error(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.yaml"

    with pytest.raises(ConfigError, match="Config file not found"):
        load_config(missing_path, current_directory=tmp_path)


def test_legacy_config_paths_are_relative_to_the_config_file(tmp_path: Path) -> None:
    config_directory = tmp_path / "course"
    config_directory.mkdir()
    config_path = config_directory / "ghtt.yaml"
    config_path.write_text(
        """
url: https://github.example.edu/course
source: template
students:
  source: data/students.csv
  field-mapping:
    username: GitHub username
    comment: "{{ record['Name'] }}"
    group: Group
repos:
  name-template: course-{student_group}
  has-issues: true
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path, current_directory=tmp_path)

    assert config.url == "https://github.example.edu/course"
    assert config.source == config_directory / "template"
    assert config.students is not None
    assert config.students.source == config_directory / "data/students.csv"
    assert config.repos.name_template == "course-{student_group}"
    assert config.repos.has_issues is True


def test_config_rejects_two_student_group_sources(tmp_path: Path) -> None:
    config_path = tmp_path / "ghtt.yaml"
    config_path.write_text(
        """
students:
  source: students.csv
  field-mapping:
    username: Username
    group: Group
    groups: Groups
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="either 'group' or 'groups'"):
        load_config(config_path, current_directory=tmp_path)


def test_schema_exposes_legacy_yaml_names() -> None:
    schema = config_schema()

    assert schema["$id"].endswith("/0.0.1.json")
    assert "default-branch" in schema["properties"]
    assert "expected-group-size" in schema["properties"]


def test_schema_command_outputs_valid_json() -> None:
    result = runner.invoke(app, ["config", "schema"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == config_schema()
