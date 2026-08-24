"""The confirmation vocabulary is part of the contract with existing courses."""

from __future__ import annotations

from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from ghtt.prompt import Aborted, Confirmer


def answers(monkeypatch: pytest.MonkeyPatch, replies: list[str]) -> list[str]:
    """Answer prompts in order and record every question that was asked."""
    asked: list[str] = []

    def fake_prompt(text: str, value_proc: Any = None, **_: Any) -> Any:
        asked.append(text)
        reply = replies.pop(0)
        # The real typer.prompt runs value_proc on what was typed, so a stub
        # that skipped it would not be testing the same contract.
        return value_proc(reply) if value_proc else reply

    monkeypatch.setattr(typer, "prompt", fake_prompt)
    return asked


def test_all_answers_for_every_remaining_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = answers(monkeypatch, ["all"])
    confirmer = Confirmer("create the repository")

    decisions = [confirmer.should_proceed(name) for name in ("one", "two", "three")]

    assert decisions == [True, True, True]
    assert len(asked) == 1


def test_none_declines_every_remaining_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = answers(monkeypatch, ["none"])
    confirmer = Confirmer("create the repository")

    decisions = [confirmer.should_proceed(name) for name in ("one", "two")]

    assert decisions == [False, False]
    assert len(asked) == 1


def test_y_and_n_decide_only_their_own_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers(monkeypatch, ["y", "n", "y"])
    confirmer = Confirmer("create the repository")

    assert [confirmer.should_proceed(name) for name in ("one", "two", "three")] == [
        True,
        False,
        True,
    ]


def test_abort_stops_the_whole_command(monkeypatch: pytest.MonkeyPatch) -> None:
    answers(monkeypatch, ["abort"])
    confirmer = Confirmer("create the repository")

    with pytest.raises(Aborted):
        confirmer.should_proceed("one")


def test_yes_asks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = answers(monkeypatch, [])
    confirmer = Confirmer("create the repository", assume_yes=True)

    assert confirmer.should_proceed("one") is True
    assert asked == []


def test_a_dry_run_asks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = answers(monkeypatch, [])
    confirmer = Confirmer("create the repository", dry_run=True)

    assert confirmer.should_proceed("one") is True
    assert asked == []


def test_a_command_that_must_always_ask_ignores_yes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = answers(monkeypatch, ["y", "y"])
    confirmer = Confirmer("delete", assume_yes=True, always_ask=True)

    assert [confirmer.should_proceed(name) for name in ("one", "two")] == [True, True]
    assert len(asked) == 2


# ==============================================================================
# What the prompt actually renders
# ==============================================================================
#
# The tests above stub the prompt to drive the decisions. These drive the real
# one, because a stub cannot notice that the choices stopped being displayed.


def ask(action: str, answers: str, always_ask: bool = False) -> str:
    """Run a real prompt through Typer's own runner and return what was shown."""
    app = typer.Typer()

    @app.command()
    def confirm() -> None:
        confirmer = Confirmer(action, always_ask=always_ask)
        typer.echo(f"decision={confirmer.should_proceed('course-ada')}")

    result = CliRunner().invoke(app, [], input=answers)
    assert result.exception is None, result.output
    return result.output


def test_the_prompt_shows_every_answer_it_accepts() -> None:
    output = ask("rename", "all\n")

    assert 'Do you want to rename "course-ada"? (y, all, n, none, abort) [n]:' in output
    assert "decision=True" in output


def test_the_delete_prompt_offers_no_answer_covering_the_rest() -> None:
    output = ask("permanently delete", "n\n", always_ask=True)

    assert (
        'Do you want to permanently delete "course-ada"? (y, n, abort) [n]:' in output
    )
    assert "decision=False" in output


def test_an_unknown_answer_is_rejected_and_asked_again() -> None:
    output = ask("rename", "maybe\ny\n")

    assert "Error: answer one of: y, all, n, none, abort" in output
    assert output.count("Do you want to rename") == 2
    assert "decision=True" in output


def test_pressing_enter_declines_that_target() -> None:
    """The default is the safe answer, so a stray newline changes nothing."""
    output = ask("rename", "\n")

    assert "decision=False" in output
