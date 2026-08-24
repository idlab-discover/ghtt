"""Git commands use ephemeral credentials without persisting them in remotes."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ghtt.git import GitError, GitTransport, require_git_repository, run_git


def test_require_git_repository_accepts_initialized_source(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    require_git_repository(tmp_path)


def test_require_git_repository_rejects_non_git_source(tmp_path: Path) -> None:
    with pytest.raises(GitError, match="expected"):
        require_git_repository(tmp_path)


def test_https_token_is_embedded_only_in_the_git_subprocess_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured_command: list[str] | None = None
    captured_environment: dict[str, str] | None = None

    def fake_run(
        command: list[str],
        cwd: Path,
        env: dict[str, str],
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal captured_command, captured_environment
        captured_command = command
        captured_environment = env
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_git(
        ["ls-remote", "https://github.example.edu/course/template.git"],
        tmp_path,
        GitTransport.HTTPS,
        "private-token",
    )

    assert result.stdout == "ok"
    assert captured_command == [
        "git",
        "ls-remote",
        "https://x-access-token:private-token@github.example.edu/course/template.git",
    ]
    assert captured_command is not None
    assert captured_environment is not None
    assert "GHTT_GIT_TOKEN" not in captured_environment


def test_ssh_does_not_embed_an_https_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured_command: list[str] | None = None
    captured_environment: dict[str, str] | None = None

    def fake_run(
        command: list[str],
        cwd: Path,
        env: dict[str, str],
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal captured_command, captured_environment
        captured_command = command
        captured_environment = env
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    run_git(["status", "--short"], tmp_path, GitTransport.SSH, "private-token")

    assert captured_environment is not None
    assert captured_command == ["git", "status", "--short"]
    assert "GHTT_GIT_TOKEN" not in captured_environment


def test_git_failures_include_the_requested_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_run(
        command: list[str],
        cwd: Path,
        env: dict[str, str],
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="private-token cannot access repository",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(GitError, match="Git could not run status") as error:
        run_git(["status"], tmp_path, token="private-token")

    assert "private-token" not in str(error.value)
