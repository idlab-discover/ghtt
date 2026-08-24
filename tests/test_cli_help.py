"""Help must work anywhere, without a config file, a token, or a network."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ghtt.cli import app

runner = CliRunner()

HELP_PAGES = [
    ["--help"],
    ["assignment", "--help"],
    ["assignment", "create-repos", "--help"],
    ["assignment", "create-pr", "--help"],
    ["assignment", "create-issues", "--help"],
    ["assignment", "pull", "--help"],
    ["assignment", "grant", "--help"],
    ["assignment", "remove-grant", "--help"],
    ["assignment", "delete-repos", "--help"],
    ["assignment", "rename-repo", "--help"],
    ["config", "--help"],
    ["config", "schema", "--help"],
    ["search", "--help"],
    ["util", "--help"],
    ["util", "grep-in", "--help"],
    ["util", "branches-to-folders", "--help"],
]


@pytest.mark.parametrize("arguments", HELP_PAGES)
def test_help_is_available_without_config(arguments: list[str]) -> None:
    result = runner.invoke(app, arguments)

    assert result.exit_code == 0, result.output
    assert result.exception is None


@pytest.mark.parametrize("arguments", HELP_PAGES)
def test_help_never_reads_a_config_file_or_opens_a_socket(
    arguments: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #5: help used to fail outside a project directory."""
    # A config file that would fail loudly if any help page read it, in a
    # directory that has nothing else a command could fall back on.
    (tmp_path / "ghtt.yaml").write_text("this: is not: valid yaml\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GHTT_TOKEN", raising=False)

    def refuse_connection(*_: object, **__: object) -> None:
        raise AssertionError("help must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse_connection)
    monkeypatch.setattr(socket.socket, "connect", refuse_connection)

    result = runner.invoke(app, arguments)

    assert result.exit_code == 0, result.output
    assert result.exception is None


def test_a_command_without_arguments_shows_its_help() -> None:
    for arguments in ([], ["assignment"], ["util"], ["config"]):
        result = runner.invoke(app, arguments)

        assert "Usage:" in result.output
