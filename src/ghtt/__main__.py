"""Entry point for ``python -m ghtt`` and the installed ``ghtt`` script."""

from __future__ import annotations

from .cli import app, main

__all__ = ["app", "main"]


if __name__ == "__main__":
    main()
