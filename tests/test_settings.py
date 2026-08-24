"""Command line over config file over built-in default, in one place."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ghtt.config import ConfigError
from ghtt.git import GitTransport
from ghtt.settings import CommonOptions, resolve_instance, resolve_settings

LEGACY_CONFIG = """
url: https://github.example.edu/algorithms-2026
source: template
default-branch: main
expected-group-size: 3
students:
  source: students.csv
  field-mapping:
    username: GitHub username
    comment: "{{ record['Name'] }}"
    group: Group
repos:
  name-template: algorithms-{student_group}
  has-issues: true
""".strip()


def write_config(directory: Path, text: str = LEGACY_CONFIG) -> Path:
    path = directory / "ghtt.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def options(**overrides: Any) -> CommonOptions:
    return CommonOptions(token="test-token", **overrides)


# ==============================================================================
# Precedence
# ==============================================================================


def test_the_config_file_supplies_what_the_command_line_omits(tmp_path: Path) -> None:
    settings = resolve_settings(options(config_path=write_config(tmp_path)))

    assert settings.connection.organization == "algorithms-2026"
    assert settings.connection.api_url == "https://github.example.edu/api/v3"
    assert settings.config.default_branch == "main"
    assert settings.config.expected_group_size == 3
    assert settings.config.repos.name_template == "algorithms-{student_group}"
    assert settings.config.repos.has_issues is True


def test_the_command_line_overrides_the_config_file(tmp_path: Path) -> None:
    settings = resolve_settings(
        options(
            config_path=write_config(tmp_path),
            organization="algorithms-2027",
            default_branch="master",
            repo_name_template="ada-{student_group}",
            has_issues=False,
        )
    )

    assert settings.connection.organization == "algorithms-2027"
    assert settings.config.default_branch == "master"
    assert settings.config.repos.name_template == "ada-{student_group}"
    assert settings.config.repos.has_issues is False


def test_built_in_defaults_apply_without_any_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    settings = resolve_settings(options(organization="algorithms-2026"))

    assert settings.connection.api_url is None
    assert settings.connection.git_url == "https://github.com"
    assert settings.config.default_branch == "master"
    assert settings.config.transport is GitTransport.HTTPS
    assert settings.config.students is None


# ==============================================================================
# Working without a config file
# ==============================================================================


def test_a_student_list_can_be_described_entirely_on_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    settings = resolve_settings(
        options(
            organization="algorithms-2026",
            students_file=Path("students.csv"),
            student_username_field="GitHub username",
            student_groups_field="Groups",
            student_comment_template="{{ record['Name'] }}",
        )
    )

    assert settings.config.students is not None
    mapping = settings.config.students.field_mapping
    assert mapping.username == "GitHub username"
    assert mapping.groups == "Groups"
    assert mapping.group is None


def test_a_student_list_file_without_a_username_column_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConfigError, match="--student-username-field"):
        resolve_settings(
            options(organization="algorithms-2026", students_file=Path("students.csv"))
        )


def test_overriding_one_group_column_clears_the_other(tmp_path: Path) -> None:
    """A config file naming `group` must not survive a `--student-groups-field`."""
    settings = resolve_settings(
        options(
            config_path=write_config(tmp_path),
            student_groups_field="Groups",
        )
    )

    assert settings.config.students is not None
    assert settings.config.students.field_mapping.group is None
    assert settings.config.students.field_mapping.groups == "Groups"


def test_setting_both_group_columns_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not both"):
        resolve_settings(
            options(
                config_path=write_config(tmp_path),
                student_group_field="Group",
                student_groups_field="Groups",
            )
        )


# ==============================================================================
# Missing values
# ==============================================================================


def test_a_missing_token_names_the_option_and_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConfigError, match="--token or set GHTT_TOKEN"):
        resolve_settings(CommonOptions(organization="algorithms-2026"))


def test_ssh_still_needs_a_token_and_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An SSH key authenticates Git, never the API, and the error must say so."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConfigError, match="goes through the GitHub API") as error:
        resolve_settings(
            CommonOptions(organization="algorithms-2026", transport=GitTransport.SSH)
        )

    assert "--transport ssh" in str(error.value)


def test_a_missing_organization_names_both_ways_to_supply_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(Exception, match="--organization"):
        resolve_settings(options())


def test_a_named_config_file_must_exist(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Config file not found"):
        resolve_settings(options(config_path=tmp_path / "absent.yaml"))


# ==============================================================================
# Transport
# ==============================================================================


def test_ssh_never_hands_the_token_to_git(tmp_path: Path) -> None:
    settings = resolve_settings(
        options(config_path=write_config(tmp_path), transport=GitTransport.SSH)
    )

    assert settings.transport is GitTransport.SSH
    assert settings.git_token is None


def test_https_hands_the_token_to_git(tmp_path: Path) -> None:
    settings = resolve_settings(options(config_path=write_config(tmp_path)))

    assert settings.git_token == "test-token"


# ==============================================================================
# Commands that need no organization
# ==============================================================================


def test_search_picks_up_the_instance_of_the_project_you_are_in(
    tmp_path: Path,
) -> None:
    url, token = resolve_instance(None, "test-token", write_config(tmp_path))

    assert url == "https://github.example.edu/algorithms-2026"
    assert token == "test-token"


def test_search_falls_back_to_github_com(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    url, _ = resolve_instance(None, "test-token", None)

    assert url == "https://github.com"
