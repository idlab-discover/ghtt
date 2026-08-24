"""Search GitHub code and optionally send a Mailgun notification about the hits."""

from __future__ import annotations

import requests
import typer
from github import Github, GithubException
from github.Repository import Repository
from pydantic import BaseModel, ConfigDict

from .defaults import MAILGUN_MESSAGE_URL
from .errors import GhttError
from .github import GitHubError, connect_github, explain_github_error, parse_github_url

# ==============================================================================
# Search Input
# ==============================================================================


class MailgunSettings(BaseModel):
    """The three values Mailgun needs before a notification can be sent."""

    model_config = ConfigDict(frozen=True)

    api_key: str
    domain: str
    to: str


class SearchError(GhttError):
    """A code search or its notification cannot complete."""


def mailgun_settings(
    api_key: str | None, domain: str | None, to: str | None
) -> MailgunSettings | None:
    """Accept a complete set of mail settings, or none at all."""
    supplied = (api_key, domain, to)
    if not any(supplied):
        return None
    if not all(supplied):
        raise SearchError(
            "Mailgun notification needs --mg-api-key, --mg-domain, and --to together."
        )
    # The `all` above proves each value is present; the assignment keeps that
    # obvious to a reader and to the type checker.
    return MailgunSettings(api_key=api_key or "", domain=domain or "", to=to or "")


# ==============================================================================
# Searching
# ==============================================================================


def matching_repositories(client: Github, query: str) -> tuple[Repository, ...]:
    """Return each distinct repository that has a code hit for the query.

    A code search reports one result per file, so several hits routinely name
    the same repository. Collapsing them first means the commit metadata below
    is fetched once per repository instead of once per matching file.
    """
    try:
        results = list(client.search_code(query))
    except GithubException as error:
        raise explain_github_error(
            error, "search code with query", repr(query)
        ) from error

    repositories: dict[str, Repository] = {}
    for result in results:
        repositories.setdefault(result.repository.full_name, result.repository)
    return tuple(repositories[name] for name in sorted(repositories))


def last_commit_author(repository: Repository) -> tuple[str, str]:
    """Return the name and email of the last commit on the default branch."""
    try:
        commit = repository.get_branch(repository.default_branch).commit
    except GithubException as error:
        raise explain_github_error(
            error, "read the last commit of", repository.full_name
        ) from error
    author = commit.commit.author
    return author.name, author.email


def notify(settings: MailgunSettings, query: str, lines: list[str]) -> None:
    """Send the search summary through Mailgun without echoing any credential."""
    body = "\n".join(lines)
    try:
        response = requests.post(
            MAILGUN_MESSAGE_URL.format(domain=settings.domain),
            auth=("api", settings.api_key),
            data={
                "from": f"ghtt <mailgun@{settings.domain}>",
                "to": settings.to,
                "subject": f"Alert! Repositories found which match query '{query}'",
                "text": body,
            },
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        # The request carries the API key, so only the status is reported back.
        status = error.response.status_code if error.response is not None else "no"
        raise SearchError(
            f"Mailgun rejected the notification ({status} response). "
            "Check --mg-api-key, --mg-domain, and --to."
        ) from error


# ==============================================================================
# Command
# ==============================================================================


def run_search(
    url: str,
    token: str,
    query: str,
    mail: MailgunSettings | None,
) -> None:
    """Print every repository matching the query and optionally mail the summary."""
    # A search spans all of GitHub, so it needs a host but never an organization.
    connection = parse_github_url(url, require_organization=False)
    if not token:
        raise GitHubError("Missing token. Supply it with --token.")
    client = connect_github(connection, token)

    typer.secho(f"# Query: '{query}'", fg=typer.colors.GREEN)
    typer.secho("# Searching for repositories..", fg=typer.colors.GREEN)

    repositories = matching_repositories(client, query)
    if not repositories:
        typer.echo("no results")
        return

    lines: list[str] = []
    for repository in repositories:
        name, email = last_commit_author(repository)
        typer.secho(repository.html_url, fg=typer.colors.RED)
        typer.echo("Metadata of last commit:")
        typer.echo(f"\tAuthor name: {name}")
        typer.echo(f"\tAuthor email: {email}\n")
        lines += [
            repository.html_url,
            "Metadata of last commit:",
            f"\tAuthor name: {name}",
            f"\tAuthor email: {email}",
            "",
        ]

    if mail is not None:
        typer.secho("Sending email", fg=typer.colors.GREEN)
        notify(mail, query, lines)
