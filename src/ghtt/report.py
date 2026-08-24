"""The outcome shared by every command that works through a list of targets."""

from __future__ import annotations

import typer
from pydantic import BaseModel, ConfigDict


class TargetReport(BaseModel):
    """What happened to every target of one command."""

    model_config = ConfigDict(frozen=True)

    processed: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()

    def summarize(self) -> None:
        """Print the closing summary so a failure is never lost in the scrollback."""
        typer.secho(
            f"\n# Done: {len(self.processed)} processed, "
            f"{len(self.skipped)} skipped, {len(self.failed)} failed.",
            fg=typer.colors.RED if self.failed else typer.colors.GREEN,
        )
        for failure in self.failed:
            typer.secho(f"  failed: {failure}", fg=typer.colors.RED, err=True)
