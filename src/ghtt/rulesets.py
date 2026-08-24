"""Protect student repositories with GitHub repository rulesets.

A branch protection rule addresses one branch that already exists, by its exact
name. That is too little for coursework: a student who cannot force-push to
``master`` can still rewrite, or delete, any branch they create afterwards. A
ruleset takes a ref pattern instead, so ``~ALL`` covers every branch of the
repository, including the ones that do not exist yet.

PyGithub does not model rulesets, so the requests are sent through the
authenticated client's own requester. That keeps the token, the Enterprise base
URL, and the :class:`GithubException` error handling of every other call.
"""

from __future__ import annotations

from typing import Any

import typer
from github import GithubException
from github.Repository import Repository

from .github import explain_github_error

# ==============================================================================
# Ruleset Definitions
# ==============================================================================

HISTORY_RULESET = "ghtt-history"
REVIEW_RULESET = "ghtt-review"

# Unlike branch protection, which leaves administrators unrestricted unless it
# is told otherwise, a ruleset binds organization owners too. Teachers own the
# organization and must stay able to repair a repository they handed out, so
# they are named as the one actor that may bypass these rules.
BYPASS_TEACHERS: list[dict[str, Any]] = [
    {"actor_type": "OrganizationAdmin", "actor_id": None, "bypass_mode": "always"}
]


def history_ruleset() -> dict[str, Any]:
    """Forbid rewriting and deleting history on every branch of the repository.

    This is the rule that makes a hand-in trustworthy: whatever a student
    pushed stays in the history, on any branch, and the branch itself cannot
    disappear either.
    """
    return {
        "name": HISTORY_RULESET,
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": BYPASS_TEACHERS,
        "conditions": {"ref_name": {"include": ["~ALL"], "exclude": []}},
        "rules": [{"type": "non_fast_forward"}, {"type": "deletion"}],
    }


def review_ruleset() -> dict[str, Any]:
    """Require a pull request before anything reaches the default branch.

    Deliberately scoped to the default branch rather than to ``~ALL``: a
    student must be free to push to a branch of their own, or the requirement
    would stop the work instead of reviewing it. Zero approvals are required,
    because a group of two cannot always approve its own work; the point is the
    pull request, not the approval.
    """
    return {
        "name": REVIEW_RULESET,
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": BYPASS_TEACHERS,
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": False,
                },
            }
        ],
    }


# ==============================================================================
# Application
# ==============================================================================


def protect_repository(
    repository: Repository, require_pull_requests: bool
) -> tuple[str, ...]:
    """Install the rulesets of one repository and report the ones that failed."""
    wanted = [history_ruleset()]
    if require_pull_requests:
        wanted.append(review_ruleset())

    failed: list[str] = []
    for ruleset in wanted:
        try:
            repository.requester.requestJsonAndCheck(
                "POST", f"{repository.url}/rulesets", input=ruleset
            )
        except GithubException as error:
            explained = explain_github_error(
                error, "protect", f"{repository.name} with ruleset {ruleset['name']}"
            )
            typer.secho(f"Warning: {explained}", fg=typer.colors.YELLOW, err=True)
            failed.append(ruleset["name"])
    return tuple(failed)
