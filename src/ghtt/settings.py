"""Turn raw command-line values plus an optional config file into one settings value.

A command reads only the resolved :class:`Settings`. That keeps the documented
precedence -- command line, then config file, then built-in default -- in a
single place instead of once per command.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .config import (
    Config,
    ConfigError,
    FieldMapping,
    RepositoryConfig,
    StudentListConfig,
    choose_value,
    load_config,
)
from .defaults import DEFAULT_GITHUB_URL
from .git import GitTransport
from .github import GitHubConnection, parse_github_url

# ==============================================================================
# Raw Command-Line Input
# ==============================================================================


class CommonOptions(BaseModel):
    """Every command-line value that can stand in for a config file entry.

    All fields are optional. ``None`` means "the user did not say", which is what
    lets a config file or a built-in default supply the value instead.
    """

    model_config = ConfigDict(frozen=True)

    config_path: Path | None = None
    url: str | None = None
    token: str | None = None
    organization: str | None = None
    source: Path | None = None
    transport: GitTransport | None = None
    default_branch: str | None = None
    enable_repo_delete: bool | None = None
    expected_group_size: int | None = None
    expected_mentors_per_group: int | None = None
    repo_name_template: str | None = None
    has_issues: bool | None = None
    has_wiki: bool | None = None
    require_pull_requests: bool | None = None
    protect_branches: tuple[str, ...] = ()
    students_file: Path | None = None
    student_username_field: str | None = None
    student_comment_template: str | None = None
    student_group_field: str | None = None
    student_groups_field: str | None = None
    mentors_file: Path | None = None
    mentor_username_field: str | None = None
    mentor_comment_template: str | None = None
    mentor_groups_field: str | None = None
    dry_run: bool = False


# ==============================================================================
# Resolved Settings
# ==============================================================================


class Settings(BaseModel):
    """The effective configuration of one command run."""

    model_config = ConfigDict(frozen=True)

    config: Config
    connection: GitHubConnection
    token: str
    dry_run: bool

    @property
    def transport(self) -> GitTransport:
        """Expose the Git transport where commands actually need it."""
        return self.config.transport

    @property
    def git_token(self) -> str | None:
        """Return the token only when the Git transport can carry it."""
        # An SSH remote authenticates with the user's key, so handing the token
        # to a Git subprocess there would leak it for no benefit.
        if self.config.transport is GitTransport.SSH:
            return None
        return self.token


# ==============================================================================
# Resolution
# ==============================================================================


def merge_student_list(
    configured: StudentListConfig | None,
    source: Path | None,
    username_field: str | None,
    comment_template: str | None,
    group_field: str | None,
    groups_field: str | None,
    role: str,
) -> StudentListConfig | None:
    """Apply command-line overrides to one configured student or mentor list.

    Both roles use exactly the same rules, so they share this function rather
    than each command repeating the precedence by hand.
    """
    supplied = (
        source,
        username_field,
        comment_template,
        group_field,
        groups_field,
    )
    if configured is None and all(value is None for value in supplied):
        return None

    resolved_source = source or (configured.source if configured else None)
    if resolved_source is None:
        raise ConfigError(
            f"Missing {role} list file. Supply it with --{role}s-file or set "
            f"{role}s.source in the config file."
        )

    mapping = configured.field_mapping if configured else None
    resolved_username = username_field or (mapping.username if mapping else None)
    if not resolved_username:
        raise ConfigError(
            f"Missing {role} username column. Supply it with --{role}-username-field."
        )

    # Both group columns describe the same thing in incompatible ways, so an
    # override of one clears the other instead of silently combining them.
    if group_field is not None or groups_field is not None:
        resolved_group = group_field
        resolved_groups = groups_field
    else:
        resolved_group = mapping.group if mapping else None
        resolved_groups = mapping.groups if mapping else None
    if resolved_group is not None and resolved_groups is not None:
        raise ConfigError(
            f"Choose either --{role}-group-field or --{role}-groups-field, not both."
        )

    return StudentListConfig(
        source=resolved_source,
        field_mapping=FieldMapping(
            username=resolved_username,
            comment=choose_value(
                comment_template, mapping.comment if mapping else None, ""
            ),
            group=resolved_group,
            groups=resolved_groups,
        ),
    )


def resolve_instance(
    url: str | None, token: str | None, config_path: Path | None
) -> tuple[str, str]:
    """Resolve the GitHub instance and token for a command that needs no organization.

    ``search`` spans all of GitHub, but it should still pick up the instance of
    the project you are standing in, exactly as the rest of ghtt does.
    """
    file_config = load_config(config_path, Path.cwd())
    if not token:
        raise ConfigError(
            "Missing GitHub token. Supply it with --token or set GHTT_TOKEN."
        )
    return choose_value(url, file_config.url, DEFAULT_GITHUB_URL), token


def resolve_settings(options: CommonOptions) -> Settings:
    """Combine command-line values, an optional config file, and built-in defaults."""
    file_config = load_config(options.config_path, Path.cwd())

    repos = RepositoryConfig(
        name_template=choose_value(
            options.repo_name_template, file_config.repos.name_template, None
        ),
        has_issues=choose_value(
            options.has_issues, file_config.repos.has_issues, False
        ),
        has_wiki=choose_value(options.has_wiki, file_config.repos.has_wiki, False),
        require_pull_requests=choose_value(
            options.require_pull_requests,
            file_config.repos.require_pull_requests,
            False,
        ),
        protect_branches=options.protect_branches or file_config.repos.protect_branches,
    )

    config = Config(
        url=choose_value(options.url, file_config.url, None),
        source=choose_value(options.source, file_config.source, None),
        transport=choose_value(
            options.transport, file_config.transport, GitTransport.HTTPS
        ),
        default_branch=choose_value(
            options.default_branch, file_config.default_branch, "master"
        ),
        enable_repo_delete=choose_value(
            options.enable_repo_delete, file_config.enable_repo_delete, False
        ),
        expected_group_size=choose_value(
            options.expected_group_size, file_config.expected_group_size, 0
        ),
        expected_mentors_per_group=choose_value(
            options.expected_mentors_per_group,
            file_config.expected_mentors_per_group,
            0,
        ),
        repos=repos,
        students=merge_student_list(
            file_config.students,
            options.students_file,
            options.student_username_field,
            options.student_comment_template,
            options.student_group_field,
            options.student_groups_field,
            role="student",
        ),
        mentors=merge_student_list(
            file_config.mentors,
            options.mentors_file,
            options.mentor_username_field,
            options.mentor_comment_template,
            None,
            options.mentor_groups_field,
            role="mentor",
        ),
    )

    url = choose_value(options.url, file_config.url, DEFAULT_GITHUB_URL)
    connection = parse_github_url(url, options.organization)

    if not options.token:
        # Selecting the SSH transport is the moment people expect their SSH key
        # to be enough, so say plainly that it covers Git but not the API.
        transport_note = (
            " --transport ssh uses your SSH key to push and fetch, but creating"
            " and configuring repositories goes through the GitHub API, which"
            " needs a token."
            if config.transport is GitTransport.SSH
            else ""
        )
        raise ConfigError(
            "Missing GitHub token. Supply it with --token or set GHTT_TOKEN."
            + transport_note
        )

    return Settings(
        config=config,
        connection=connection,
        token=options.token,
        dry_run=options.dry_run,
    )
