"""The one exception family that the command line turns into readable output."""

from __future__ import annotations


class GhttError(Exception):
    """An expected user, configuration, Git, or GitHub failure.

    Anything raised from this family is a problem the user can act on, so the
    command line prints its message instead of a traceback. Programming
    mistakes deliberately keep their traceback so they are never mistaken for
    ordinary misconfiguration.
    """
