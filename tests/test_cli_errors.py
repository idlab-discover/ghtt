"""An expected failure gets a message and a nonzero exit, never a traceback."""

from __future__ import annotations

from pathlib import Path

import pytest
import requests
from github import GithubException
from typer.testing import CliRunner

from ghtt.cli import app

runner = CliRunner()

CONFIG = """
url: https://github.example.edu/algorithms-2026
students:
  source: students.csv
  field-mapping:
    username: Username
    comment: "{{ record['Name'] }}"
    group: Group
""".strip()

STUDENTS = "Username,Name,Group\nada,Ada Lovelace,Team 1\n"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "ghtt.yaml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / "students.csv").write_text(STUDENTS, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_an_unreachable_instance_names_the_url_and_the_network(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise requests.ConnectionError("Failed to resolve 'github.example.edu'")

    monkeypatch.setattr("ghtt.assignment.connect_github", refuse)

    result = runner.invoke(app, ["assignment", "--token", "test-token", "grant"])

    assert result.exit_code == 1
    assert "cannot reach GitHub" in result.output
    assert "--url" in result.output
    assert "Traceback" not in result.output


def test_an_unexpected_api_failure_still_explains_itself(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise GithubException(500, "Internal Server Error", {})

    monkeypatch.setattr("ghtt.assignment.connect_github", refuse)

    result = runner.invoke(app, ["assignment", "--token", "test-token", "grant"])

    assert result.exit_code == 1
    assert "GitHub returned 500" in result.output
    assert "Traceback" not in result.output


def test_a_bad_config_file_names_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "ghtt.yaml").write_text(
        "students:\n  unknown-key: 1\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["assignment", "--token", "test-token", "grant"])

    assert result.exit_code == 1
    assert "Invalid config in" in result.output
    assert "Traceback" not in result.output


def test_a_missing_student_list_file_names_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "ghtt.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["assignment", "--token", "test-token", "grant"])

    assert result.exit_code == 1
    assert "student list file not found" in result.output
    assert "students.csv" in result.output


def test_a_malformed_content_file_mapping_shows_how_to_write_it(
    project: Path,
) -> None:
    result = runner.invoke(
        app,
        [
            "assignment",
            "--token",
            "test-token",
            "create-pr",
            "--branch",
            "kubeconfig",
            "--title",
            "Cluster access",
            "--body",
            "Merge this.",
            "--content-file",
            "kubeconfigs/team-1.yaml",
        ],
    )

    assert result.exit_code == 1
    assert "SOURCE=DESTINATION" in result.output
    assert "Traceback" not in result.output


def test_an_unknown_content_placeholder_is_refused_before_any_request(
    project: Path,
) -> None:
    result = runner.invoke(
        app,
        [
            "assignment",
            "--token",
            "test-token",
            "create-repos",
            "--content-dir",
            "handouts/{student_name}",
        ],
    )

    assert result.exit_code == 1
    assert "student_name" in result.output
    assert "{student_username}" in result.output
    assert "Traceback" not in result.output
