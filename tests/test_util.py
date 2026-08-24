"""Local utilities behave predictably and never remove files on their own."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ghtt.cli import app
from ghtt.errors import GhttError
from ghtt.util import UtilityError, branches_to_folders, grep_in

from .local_git import make_repository

runner = CliRunner()


# ==============================================================================
# grep-in
# ==============================================================================


def test_grep_in_keeps_the_header_by_default(tmp_path: Path) -> None:
    path = tmp_path / "students.csv"
    path.write_text("Username,Group\nada,Team 1\nbert,Team 2\n", encoding="utf-8")

    result = runner.invoke(app, ["util", "grep-in", str(path), "Team 1"])

    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == ["Username,Group", "ada,Team 1"]


def test_grep_in_omits_the_header_on_request(tmp_path: Path) -> None:
    path = tmp_path / "students.csv"
    path.write_text("Username,Group\nada,Team 1\nbert,Team 2\n", encoding="utf-8")

    result = runner.invoke(
        app, ["util", "grep-in", str(path), "Team 1,Team 2", "--no-header"]
    )

    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == ["ada,Team 1", "bert,Team 2"]


def test_grep_in_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(UtilityError, match="File not found"):
        grep_in(tmp_path / "absent.csv", "ada", include_header=True)


def test_grep_in_reports_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "students.csv"
    path.write_text("", encoding="utf-8")

    with pytest.raises(UtilityError, match="File is empty"):
        grep_in(path, "ada", include_header=True)


def test_grep_in_exits_nonzero_with_a_message_instead_of_a_traceback(
    tmp_path: Path,
) -> None:
    result = runner.invoke(
        app, ["util", "grep-in", str(tmp_path / "absent.csv"), "ada"]
    )

    assert result.exit_code == 1
    assert "File not found" in result.output
    assert "Traceback" not in result.output


# ==============================================================================
# branches-to-folders
# ==============================================================================


def test_branches_to_folders_expands_every_branch(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template", ("ada", "bert"))

    report = branches_to_folders(
        source, at=None, remove_repository=False, dry_run=False
    )

    expanded = tmp_path / "template.expanded"
    assert report.failed == ()
    assert sorted(report.processed) == ["ada", "bert", "master"]
    assert (expanded / "ada" / "ada.txt").read_text(encoding="utf-8") == "ada"
    assert (expanded / "bert" / ".git").is_dir()


def test_branches_to_folders_can_drop_the_git_directory(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template", ("ada",))

    branches_to_folders(source, at=None, remove_repository=True, dry_run=False)

    assert not (tmp_path / "template.expanded" / "ada" / ".git").exists()
    assert (tmp_path / "template.expanded" / "ada" / "ada.txt").exists()


def test_branches_to_folders_refuses_an_existing_destination(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template", ("ada",))
    existing = tmp_path / "template.expanded"
    existing.mkdir()
    (existing / "important.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(UtilityError, match="already exists"):
        branches_to_folders(source, at=None, remove_repository=False, dry_run=False)

    assert (existing / "important.txt").exists()


def test_branches_to_folders_rejects_a_source_without_git(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    with pytest.raises(GhttError, match="not a Git repository"):
        branches_to_folders(plain, at=None, remove_repository=False, dry_run=False)


def test_branches_to_folders_dry_run_writes_nothing(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template", ("ada",))

    report = branches_to_folders(source, at=None, remove_repository=False, dry_run=True)

    assert not (tmp_path / "template.expanded").exists()
    assert sorted(report.skipped) == ["ada", "master"]
    assert report.processed == ()


def test_branches_to_folders_reports_a_moment_without_a_commit(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template", ("ada",))

    report = branches_to_folders(
        source, at="1999-01-01", remove_repository=False, dry_run=False
    )

    assert sorted(report.failed) == ["ada", "master"]
    assert report.processed == ()
