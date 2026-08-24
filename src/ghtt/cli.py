"""The command line of ghtt.

This module owns every option name, help text, and exit code. It resolves what
the user typed and hands the result to a workflow function elsewhere; no GitHub
or Git work happens here.

Building the command tree must stay free of side effects. Typer runs this same
code to render ``--help``, and help is guaranteed to work without a config file,
a token, a prompt, or a network connection.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import requests
import typer
from github import GithubException

from .access import grant_access, remove_access
from .assignment import TargetSelection, prepare_assignment
from .config import config_schema
from .errors import GhttError
from .git import GitTransport
from .github import explain_github_error
from .issues import create_issues
from .pull import pull_repositories
from .pull_requests import create_pull_requests
from .report import TargetReport
from .repositories import (
    create_repositories,
    delete_repositories,
    rename_repositories,
    require_deletion_enabled,
)
from .search import mailgun_settings, run_search
from .settings import CommonOptions, resolve_instance, resolve_settings
from .templates import build_content_plan
from .util import branches_to_folders, grep_in

# ==============================================================================
# Error Handling
# ==============================================================================


def reports_errors[**P, R](command: Callable[P, R]) -> Callable[P, R]:
    """Turn an expected ghtt failure into a readable message and a failing exit.

    Every command needs this, and a decorator keeps the twelve command bodies
    free of an identical `try`/`except` block. Anything not caught here keeps
    its traceback: that means a bug, not a mistake the user can correct.
    """

    @functools.wraps(command)
    def wrapper(*arguments: P.args, **keywords: P.kwargs) -> R:
        try:
            return command(*arguments, **keywords)
        except GhttError as error:
            typer.secho(f"Error: {error}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from error
        except requests.RequestException as error:
            # An unreachable instance is a wrong URL, a missing VPN, or an
            # offline laptop far more often than it is a bug in ghtt.
            typer.secho(
                "Error: cannot reach GitHub. Check --url, your network "
                "connection, and any VPN a GitHub Enterprise instance needs.\n"
                f"  {type(error).__name__}: {first_line(error)}",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1) from error
        except GithubException as error:
            # A last resort for a call whose own handler did not expect this
            # status: still a message about the request, never a traceback.
            explained = explain_github_error(error, "complete a request to", "GitHub")
            typer.secho(f"Error: {explained}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from error

    return wrapper


def first_line(error: Exception) -> str:
    """Keep the useful first line of a long, nested transport error."""
    return str(error).strip().splitlines()[0] if str(error).strip() else "no detail"


def finish(report: TargetReport) -> None:
    """Print the closing summary and fail the command if any target failed."""
    report.summarize()
    if report.failed:
        raise typer.Exit(code=1)


# ==============================================================================
# Shared Option Types
# ==============================================================================
#
# Each option is declared once here and reused by every command that accepts it,
# so a help text or a short alias can never drift between two commands.

ConfigPathOption = Annotated[
    Path | None,
    typer.Option(
        "--config",
        help="Optional ghtt.yaml file. Loaded only when a command needs a value.",
    ),
]
UrlOption = Annotated[
    str | None,
    typer.Option(
        "--url",
        "-u",
        help=(
            "URL of the GitHub instance. The legacy form that ends in the "
            "organization, such as https://github.example.edu/my-course, is "
            "still accepted. Defaults to https://github.com."
        ),
    ),
]
TokenOption = Annotated[
    str | None,
    typer.Option(
        "--token",
        "-t",
        envvar="GHTT_TOKEN",
        help="GitHub personal access token.",
        show_envvar=True,
    ),
]
OrganizationOption = Annotated[
    str | None,
    typer.Option(
        "--organization",
        help="GitHub organization that holds the student repositories.",
    ),
]
SourceOption = Annotated[
    Path | None,
    typer.Option(
        "--source",
        "-s",
        help="Local Git repository holding the assignment source code.",
    ),
]
StudentsFilterOption = Annotated[
    str | None,
    typer.Option(
        "--students",
        help=(
            "Comma-separated usernames to filter the configured student list. "
            "This is a filter, not a student list: a repository is selected "
            "when it matches every filter you supply. Defaults to all students."
        ),
    ),
]
GroupsFilterOption = Annotated[
    str | None,
    typer.Option(
        "--groups",
        help=(
            "Comma-separated group names to filter the configured student list. "
            "This is a filter, not a group list: a repository is selected when "
            "it matches every filter you supply. Defaults to all groups."
        ),
    ),
]
YesOption = Annotated[
    bool,
    typer.Option(
        "--yes",
        help="Process all selected repositories without asking for each one.",
    ),
]
# Both content options accept the placeholders of a repository name, which is
# what lets one command hand every student or group a file of their own.
ContentDirOption = Annotated[
    list[str] | None,
    typer.Option(
        "--content-dir",
        help=(
            "Directory of files to write into each repository, keeping the "
            "paths relative to it, so content/docs/task.md lands at "
            "docs/task.md. Repeatable: a later directory replaces a file an "
            "earlier one wrote. May contain {organization}, {student_username}, "
            "and {student_group}, as in handouts/lab3/{student_group}, to give "
            "each student or group files only they receive."
        ),
    ),
]
ContentFileOption = Annotated[
    list[str] | None,
    typer.Option(
        "--content-file",
        help=(
            "One file to write into each repository, as SOURCE=DESTINATION, for "
            "example 'kubeconfigs/{student_group}.yaml=.kube/config'. Both "
            "halves accept the same placeholders as --content-dir. Repeatable, "
            "and applied after every --content-dir."
        ),
    ),
]


# ==============================================================================
# Command Tree
# ==============================================================================

app = typer.Typer(
    help="Manage GitHub-based coursework and exams.",
    no_args_is_help=True,
)
assignment_app = typer.Typer(
    help=(
        "Manage student or group repositories.\n\n"
        "Options shared by all assignment commands are given before the "
        "subcommand, for example: ghtt assignment --token TOKEN create-repos"
    ),
    no_args_is_help=True,
)
config_app = typer.Typer(
    help="Inspect ghtt config support.",
    no_args_is_help=True,
)
util_app = typer.Typer(
    help="Run local file and Git utilities.",
    no_args_is_help=True,
)
app.add_typer(assignment_app, name="assignment")
app.add_typer(config_app, name="config")
app.add_typer(util_app, name="util")


@app.callback()
def cli() -> None:
    """Run ghtt commands."""
    # Deliberately empty. Commands load config only once they know they need it,
    # which is what keeps every nested --help page offline.


# ==============================================================================
# Assignment Options
# ==============================================================================
#
# The assignment group carries the settings that apply to every one of its
# subcommands. That preserves the legacy `ghtt assignment --token X grant` call
# style and keeps each subcommand signature down to its own options.


@assignment_app.callback()
def assignment(
    context: typer.Context,
    config: ConfigPathOption = None,
    url: UrlOption = None,
    token: TokenOption = None,
    organization: OrganizationOption = None,
    transport: Annotated[
        GitTransport | None,
        typer.Option(
            "--transport",
            help=(
                "Git transport for pushing and fetching. https uses --token; "
                "ssh uses your own SSH key. A token is required either way, "
                "because the GitHub API cannot use an SSH key. Defaults to https."
            ),
        ),
    ] = None,
    default_branch: Annotated[
        str | None,
        typer.Option(
            "--default-branch",
            help=(
                "Branch used as the initial branch of new repositories and as "
                "the base branch of pull requests. Defaults to master."
            ),
        ),
    ] = None,
    enable_repo_delete: Annotated[
        bool | None,
        typer.Option(
            "--enable-repo-delete/--no-enable-repo-delete",
            help="Second opt-in required by delete-repos.",
        ),
    ] = None,
    expected_group_size: Annotated[
        int | None,
        typer.Option(
            "--expected-group-size",
            help="Students expected per repository. 0 disables the check.",
        ),
    ] = None,
    expected_mentors_per_group: Annotated[
        int | None,
        typer.Option(
            "--expected-mentors-per-group",
            help="Mentors expected per repository. 0 disables the check.",
        ),
    ] = None,
    repo_name_template: Annotated[
        str | None,
        typer.Option(
            "--repo-name-template",
            help=(
                "Repository name pattern. Supports {organization}, "
                "{student_username}, and {student_group}."
            ),
        ),
    ] = None,
    has_issues: Annotated[
        bool | None,
        typer.Option(
            "--has-issues/--no-has-issues", help="Enable issues on new repositories."
        ),
    ] = None,
    has_wiki: Annotated[
        bool | None,
        typer.Option(
            "--has-wiki/--no-has-wiki", help="Enable wikis on new repositories."
        ),
    ] = None,
    require_pull_requests: Annotated[
        bool | None,
        typer.Option(
            "--require-pull-requests/--no-require-pull-requests",
            help="Require a pull request before merging into a protected branch.",
        ),
    ] = None,
    protect_branch: Annotated[
        list[str] | None,
        typer.Option(
            "--protect-branch",
            help=(
                "Additional branch to protect, by exact name. Repeatable. The "
                "default branch is always protected."
            ),
        ),
    ] = None,
    students_file: Annotated[
        Path | None,
        typer.Option("--students-file", help="CSV file listing the students."),
    ] = None,
    student_username_field: Annotated[
        str | None,
        typer.Option(
            "--student-username-field",
            help="CSV column holding GitHub usernames.",
        ),
    ] = None,
    student_comment_template: Annotated[
        str | None,
        typer.Option(
            "--student-comment-template",
            help=(
                "Jinja template for a student's part of the repository "
                "description, for example \"{{ record['Name'] }}\"."
            ),
        ),
    ] = None,
    student_group_field: Annotated[
        str | None,
        typer.Option(
            "--student-group-field",
            help="CSV column holding one group name per student.",
        ),
    ] = None,
    student_groups_field: Annotated[
        str | None,
        typer.Option(
            "--student-groups-field",
            help=(
                "CSV column holding a comma-separated list of groups. A student "
                "joins the repository of every group listed."
            ),
        ),
    ] = None,
    mentors_file: Annotated[
        Path | None,
        typer.Option("--mentors-file", help="CSV file listing the mentors."),
    ] = None,
    mentor_username_field: Annotated[
        str | None,
        typer.Option("--mentor-username-field", help="Mentor username column."),
    ] = None,
    mentor_comment_template: Annotated[
        str | None,
        typer.Option(
            "--mentor-comment-template", help="Jinja template for a mentor description."
        ),
    ] = None,
    mentor_groups_field: Annotated[
        str | None,
        typer.Option(
            "--mentor-groups-field",
            help="CSV column holding the groups a mentor guides.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Show the plan and every intended change without performing any.",
        ),
    ] = False,
) -> None:
    """Manage student or group repositories."""
    # Only recording what was typed. Reading files or contacting GitHub here
    # would run during `--help` of every subcommand.
    context.obj = CommonOptions(
        config_path=config,
        url=url,
        token=token,
        organization=organization,
        transport=transport,
        default_branch=default_branch,
        enable_repo_delete=enable_repo_delete,
        expected_group_size=expected_group_size,
        expected_mentors_per_group=expected_mentors_per_group,
        repo_name_template=repo_name_template,
        has_issues=has_issues,
        has_wiki=has_wiki,
        require_pull_requests=require_pull_requests,
        protect_branches=tuple(protect_branch or ()),
        students_file=students_file,
        student_username_field=student_username_field,
        student_comment_template=student_comment_template,
        student_group_field=student_group_field,
        student_groups_field=student_groups_field,
        mentors_file=mentors_file,
        mentor_username_field=mentor_username_field,
        mentor_comment_template=mentor_comment_template,
        mentor_groups_field=mentor_groups_field,
        dry_run=dry_run,
    )


def options_of(context: typer.Context, source: Path | None = None) -> CommonOptions:
    """Return the assignment options, letting a subcommand override --source."""
    options = context.obj
    if not isinstance(
        options, CommonOptions
    ):  # pragma: no cover - Typer always sets it
        raise GhttError("Assignment options were not initialized.")
    if source is None:
        return options
    return options.model_copy(update={"source": source})


# ==============================================================================
# Repository And Content Commands
# ==============================================================================


@assignment_app.command("create-repos")
@reports_errors
def create_repos(
    context: typer.Context,
    source: SourceOption = None,
    content_dir: ContentDirOption = None,
    content_file: ContentFileOption = None,
    students: StudentsFilterOption = None,
    groups: GroupsFilterOption = None,
    yes: YesOption = False,
) -> None:
    """Create a private repository per student or group from a source repository.

    Each repository receives a copy of the source with its .jinja files rendered
    for that student or group, and its default branch is protected so students
    cannot rewrite history. An existing repository is never overwritten.

    --content-dir and --content-file add files that live outside the source
    repository, such as a credential or a dataset generated per group. They are
    committed on top of the source, so they are there from the first day.

    This does not give students access; see `ghtt assignment grant`.
    """
    settings = resolve_settings(options_of(context, source))
    selection = TargetSelection(students=students, groups=groups, assume_yes=yes)
    content = build_content_plan(content_dir, content_file)
    finish(create_repositories(prepare_assignment(settings, selection), yes, content))


@assignment_app.command("create-pr")
@reports_errors
def create_pr(
    context: typer.Context,
    branch: Annotated[
        str,
        typer.Option("--branch", help="Branch to create in the student repositories."),
    ],
    title: Annotated[str, typer.Option("--title", help="Title of the pull request.")],
    body: Annotated[
        str, typer.Option("--body", help="Body of the pull request (the message).")
    ],
    source: SourceOption = None,
    branch_already_pushed: Annotated[
        bool,
        typer.Option(
            "--branch-already-pushed",
            "-B",
            help="The branch is already pushed, so only open the pull requests.",
        ),
    ] = False,
    content_dir: ContentDirOption = None,
    content_file: ContentFileOption = None,
    force_push: Annotated[
        bool,
        typer.Option(
            "--force-push",
            help="Overwrite the branch if it already exists with other history.",
        ),
    ] = False,
    students: StudentsFilterOption = None,
    groups: GroupsFilterOption = None,
    yes: YesOption = False,
) -> None:
    """Push a branch to the student repositories and open a pull request in each.

    Without --content-dir and --content-file the same branch is pushed from
    --source to every repository, which is how a class-wide update is handed out.

    With them, only those files are written into each repository, resolved and
    rendered for that student or group, on a branch cut from the repository's
    own default branch. Use it to hand out per-student credentials, a file only
    one group may have, or a correction to one file without touching anything
    else the student has changed. This mode needs no --source.

    The pull request is opened from --branch into the default branch. An open
    pull request for the same branch pair is reused rather than duplicated:
    pushing to its branch already updates it.
    """
    settings = resolve_settings(options_of(context, source))
    selection = TargetSelection(students=students, groups=groups, assume_yes=yes)
    content = build_content_plan(content_dir, content_file)
    finish(
        create_pull_requests(
            prepare_assignment(settings, selection),
            branch,
            title,
            body,
            branch_already_pushed,
            content,
            force_push,
            yes,
        )
    )


@assignment_app.command("create-issues")
@reports_errors
def create_issues_command(
    context: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(
            help=(
                "YAML file describing the milestones and issues to create. It is "
                "a list of entries, each with type: milestone or type: issue, and "
                "it is rendered as a Jinja template for every repository. See "
                "docs/examples/project-config/lab1-assignment.yaml."
            )
        ),
    ],
    students: StudentsFilterOption = None,
    groups: GroupsFilterOption = None,
    yes: YesOption = False,
) -> None:
    """Create or update the milestones and issues described by PATH.

    An entry that already exists with the same title is updated only when it
    differs, so running this again after editing the template is safe.
    """
    settings = resolve_settings(options_of(context))
    selection = TargetSelection(students=students, groups=groups, assume_yes=yes)
    finish(create_issues(prepare_assignment(settings, selection), path, yes))


@assignment_app.command()
@reports_errors
def pull(
    context: typer.Context,
    source: SourceOption = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Replace a local branch that has diverged from the repository.",
        ),
    ] = False,
    students: StudentsFilterOption = None,
    groups: GroupsFilterOption = None,
    yes: YesOption = False,
) -> None:
    """Fetch each student repository into a local branch and show its last commit.

    Nothing is checked out, so your worktree and unrelated branches are left
    alone. Use `ghtt util branches-to-folders` to unpack the branches afterwards.
    """
    settings = resolve_settings(options_of(context, source))
    selection = TargetSelection(students=students, groups=groups, assume_yes=yes)
    finish(pull_repositories(prepare_assignment(settings, selection), force, yes))


# ==============================================================================
# Access Commands
# ==============================================================================


@assignment_app.command()
@reports_errors
def grant(
    context: typer.Context,
    read_only: Annotated[
        bool,
        typer.Option(
            "--read-only",
            help=(
                "Give pull access instead of push access. Students can still "
                "open and answer issues."
            ),
        ),
    ] = False,
    students: StudentsFilterOption = None,
    groups: GroupsFilterOption = None,
    yes: YesOption = False,
) -> None:
    """Grant each student the collaborator role on their own repository.

    Students who already have access have their access level set again, so
    --read-only downgrades existing push access to pull access.
    """
    settings = resolve_settings(options_of(context))
    selection = TargetSelection(students=students, groups=groups, assume_yes=yes)
    finish(grant_access(prepare_assignment(settings, selection), read_only, yes))


@assignment_app.command("remove-grant")
@reports_errors
def remove_grant(
    context: typer.Context,
    students: StudentsFilterOption = None,
    groups: GroupsFilterOption = None,
    yes: YesOption = False,
) -> None:
    """Remove students' access to their repository and cancel pending invitations.

    To keep read-only access instead of removing access entirely, use
    `ghtt assignment grant --read-only`.
    """
    settings = resolve_settings(options_of(context))
    selection = TargetSelection(students=students, groups=groups, assume_yes=yes)
    finish(remove_access(prepare_assignment(settings, selection), yes))


# ==============================================================================
# Destructive Commands
# ==============================================================================


@assignment_app.command("delete-repos")
@reports_errors
def delete_repos(
    context: typer.Context,
    destroy_data: Annotated[
        bool,
        typer.Option(
            "--destroy-data",
            help="Confirm that this command may irrecoverably destroy data.",
        ),
    ] = False,
    students: StudentsFilterOption = None,
    groups: GroupsFilterOption = None,
) -> None:
    """Permanently delete the selected repositories and all of their history.

    This needs two opt-ins: --destroy-data on the command line and
    --enable-repo-delete (or 'enable-repo-delete: true' in ghtt.yaml). Every
    repository is confirmed separately and --yes is deliberately not accepted.

    Consider `ghtt assignment rename-repo` instead: renaming keeps the data.
    """
    settings = resolve_settings(options_of(context))
    require_deletion_enabled(settings, destroy_data)
    selection = TargetSelection(students=students, groups=groups, assume_yes=False)
    finish(delete_repositories(prepare_assignment(settings, selection)))


@assignment_app.command("rename-repo")
@reports_errors
def rename_repo(
    context: typer.Context,
    match: Annotated[
        str,
        typer.Option(
            "--match",
            help='Regular expression matching repository names, e.g. "studnt-(.*)".',
        ),
    ],
    replace: Annotated[
        str,
        typer.Option(
            "--replace",
            help=(
                "New name. It may use \\1, \\2, ... to refer to the groups "
                'captured by --match, e.g. "student-\\1".'
            ),
        ),
    ],
    yes: YesOption = False,
) -> None:
    """Rename organization repositories whose name matches a regular expression.

    Unlike the other assignment commands this one works on every repository in
    the organization, not only on those derived from the student list.
    """
    settings = resolve_settings(options_of(context))
    finish(rename_repositories(settings, match, replace, yes))


# ==============================================================================
# Config Commands
# ==============================================================================


@config_app.command()
def schema() -> None:
    """Print the JSON Schema of ghtt.yaml for this ghtt release."""
    typer.echo(json.dumps(config_schema(), indent=2, sort_keys=True))


# ==============================================================================
# Search
# ==============================================================================


@app.command()
@reports_errors
def search(
    query: Annotated[
        str,
        typer.Option(
            "--query",
            "-q",
            help='GitHub code search query, for example "Allkit.h in:path".',
        ),
    ],
    url: UrlOption = None,
    token: TokenOption = None,
    config: ConfigPathOption = None,
    mg_api_key: Annotated[
        str | None, typer.Option("--mg-api-key", help="Mailgun API key.")
    ] = None,
    mg_domain: Annotated[
        str | None, typer.Option("--mg-domain", help="Mailgun domain name.")
    ] = None,
    to: Annotated[
        str | None, typer.Option("--to", help="Email address to send the alert to.")
    ] = None,
) -> None:
    """Search GitHub code and print the last committer of each matching repository.

    For the query syntax see
    https://docs.github.com/en/search-github/searching-on-github/searching-code

    All three Mailgun options must be given together to send a notification.

    Examples:

      ghtt search -t TOKEN -u github.example.edu -q "Allkit.h in:path"

      ghtt search -t TOKEN -q "Allkit.h in:path" --mg-api-key KEY
      --mg-domain mg.example.edu --to teacher@example.edu
    """
    instance_url, instance_token = resolve_instance(url, token, config)
    run_search(
        instance_url,
        instance_token,
        query,
        mailgun_settings(mg_api_key, mg_domain, to),
    )


# ==============================================================================
# Utilities
# ==============================================================================


@util_app.command("grep-in")
@reports_errors
def grep_in_command(
    path: Annotated[Path, typer.Argument(help="File to search.")],
    strings: Annotated[
        str, typer.Argument(help="Comma-separated strings to search for.")
    ],
    no_header: Annotated[
        bool,
        typer.Option("--no-header", help="Do not print the first line of the file."),
    ] = False,
) -> None:
    """Print each line of PATH that contains one of the comma-separated STRINGS.

    The first line is treated as a header and always printed, because a matching
    CSV row is only readable next to its column names. Use --no-header to omit it.
    """
    grep_in(path, strings, include_header=not no_header)


@util_app.command("branches-to-folders")
@reports_errors
def branches_to_folders_command(
    source: Annotated[Path, typer.Argument(help="Local Git repository to expand.")],
    at: Annotated[
        str | None,
        typer.Option(
            "--at",
            "-a",
            help=(
                "Check out the newest commit at or before this moment, for "
                'example "2026-01-31 09:00".'
            ),
        ),
    ] = None,
    rm_repo: Annotated[
        bool,
        typer.Option(
            "--rm-repo",
            "-r",
            help="Keep only the files of each branch, without its .git directory.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="List the branches without writing anything."),
    ] = False,
) -> None:
    """Clone every local branch of SOURCE into its own folder in SOURCE.expanded.

    The destination must not exist yet; ghtt never deletes files for you.
    """
    finish(branches_to_folders(source, at, rm_repo, dry_run))


# ==============================================================================
# Installed Entry Point
# ==============================================================================


def main() -> None:
    """Launch the Typer application from the installed console script."""
    app()
