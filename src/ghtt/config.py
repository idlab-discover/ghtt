"""Typed loading of optional legacy ``ghtt.yaml`` project defaults."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .defaults import CONFIG_FILENAME
from .errors import GhttError
from .git import GitTransport

# ==============================================================================
# Config Shape
# ==============================================================================
#
# These models deliberately mirror the documented legacy YAML names. Keeping the
# aliases beside the typed fields makes the accepted file format easy to audit
# and lets Pydantic generate the matching JSON Schema without a second format.


class ConfigError(GhttError):
    """A config file cannot safely supply command defaults."""


class FieldMapping(BaseModel):
    """Map student-list CSV fields onto a person record."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    username: str
    comment: str = ""
    group: str | None = None
    groups: str | None = None


class StudentListConfig(BaseModel):
    """Describe a student or mentor list CSV file and its mapped fields."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: Path
    field_mapping: Annotated[FieldMapping, Field(alias="field-mapping")]


class RepositoryConfig(BaseModel):
    """Defaults applied while creating student repositories."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name_template: Annotated[str | None, Field(alias="name-template")] = None
    has_issues: Annotated[bool, Field(alias="has-issues")] = False
    has_wiki: Annotated[bool, Field(alias="has-wiki")] = False
    require_pull_requests: Annotated[bool, Field(alias="require-pull-requests")] = False
    # The default branch is always protected. These are additional branches,
    # named exactly, that should receive the same protection.
    protect_branches: Annotated[tuple[str, ...], Field(alias="protect-branches")] = ()


class Config(BaseModel):
    """All supported legacy config defaults for one coursework project."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    url: str | None = None
    source: Path | None = None
    transport: GitTransport = GitTransport.HTTPS
    default_branch: Annotated[str, Field(alias="default-branch")] = "master"
    enable_repo_delete: Annotated[bool, Field(alias="enable-repo-delete")] = False
    expected_group_size: Annotated[int, Field(alias="expected-group-size")] = 0
    expected_mentors_per_group: Annotated[
        int, Field(alias="expected-mentors-per-group")
    ] = 0
    repos: RepositoryConfig = Field(default_factory=RepositoryConfig)
    students: StudentListConfig | None = None
    mentors: StudentListConfig | None = None

    @model_validator(mode="after")
    def reject_ambiguous_student_groups(self) -> Config:
        """Avoid silently assigning a student from two incompatible group sources."""
        if self.students is None:
            return self

        mapping = self.students.field_mapping
        if mapping.group is not None and mapping.groups is not None:
            raise ValueError(
                "students.field-mapping may set either 'group' or 'groups', not both"
            )
        return self


# ==============================================================================
# Config Loading
# ==============================================================================


def choose_value[T](command_line: T | None, config: T | None, built_in: T) -> T:
    """Apply the documented command-line, config, then built-in precedence."""
    if command_line is not None:
        return command_line
    if config is not None:
        return config
    return built_in


def load_config(
    config_path: Path | None,
    current_directory: Path,
) -> Config:
    """Load the explicitly selected or local optional project config."""
    selected_path = config_path or current_directory / CONFIG_FILENAME
    explicit_selection = config_path is not None

    # A local config is a convenience, not a requirement. An explicitly named
    # config, however, is an intentional request and should never be ignored.
    if not selected_path.exists():
        if explicit_selection:
            raise ConfigError(f"Config file not found: {selected_path}")
        return Config()
    if not selected_path.is_file():
        raise ConfigError(f"Config path is not a file: {selected_path}")

    # Parse YAML before constructing models so malformed YAML receives a
    # file-specific error instead of a generic validation failure.
    try:
        with selected_path.open(encoding="utf-8") as file:
            raw_config = yaml.safe_load(file)
    except OSError as error:
        raise ConfigError(
            f"Cannot read config file {selected_path}: {error}"
        ) from error
    except yaml.YAMLError as error:
        raise ConfigError(
            f"Invalid YAML in config file {selected_path}: {error}"
        ) from error

    if raw_config is None:
        raw_config = {}
    if not isinstance(raw_config, dict):
        raise ConfigError(f"Config file {selected_path} must contain a YAML mapping")

    # Pydantic now checks the documented structure, including unknown keys.
    try:
        config = Config.model_validate(raw_config)
    except ValidationError as error:
        raise ConfigError(f"Invalid config in {selected_path}: {error}") from error

    # Relative paths describe project files, so they belong to the config file
    # rather than whichever directory happened to run ghtt.
    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else (selected_path.parent / path).resolve()

    updates: dict[str, object] = {}
    if config.source is not None:
        updates["source"] = resolve(config.source)
    for role in ("students", "mentors"):
        student_list = getattr(config, role)
        if student_list is not None:
            updates[role] = student_list.model_copy(
                update={"source": resolve(student_list.source)}
            )
    return config.model_copy(update=updates)


# ==============================================================================
# Schema Publication
# ==============================================================================


def config_schema() -> dict[str, Any]:
    """Return the release-specific JSON Schema for supported project defaults."""
    schema = Config.model_json_schema(by_alias=True)
    schema["$id"] = (
        f"https://github.com/idlab-discover/ghtt/schemas/{version('ghtt')}.json"
    )
    return schema
