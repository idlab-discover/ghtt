"""Render Jinja templates with the documented data of one repository target."""

from __future__ import annotations

from pathlib import Path
from string import Formatter

import jinja2
from pydantic import BaseModel, ConfigDict

from .defaults import (
    CONTENT_FILE_SEPARATOR,
    NAME_TEMPLATE_PLACEHOLDERS,
    TEMPLATE_SUFFIX,
)
from .errors import GhttError
from .student_list import RepositoryTarget


class RenderError(GhttError):
    """A source template cannot be rendered for a repository target."""


def template_data(target: RepositoryTarget, clone_url: str) -> dict[str, object]:
    """Return the complete set of variables available to a source template.

    This mapping is a documented contract: teachers write templates against it,
    so names are added here rather than assembled differently per command.
    """
    return {
        "clone_url": clone_url,
        "organization": target.organization,
        "group": target.group,
        "students": list(target.students),
        "mentors": list(target.mentors),
        "repo": target,
    }


def render_text(template_text: str, target: RepositoryTarget, clone_url: str) -> str:
    """Render one template string for a target, failing on any unknown variable."""
    environment = jinja2.Environment(
        undefined=jinja2.StrictUndefined, keep_trailing_newline=True
    )
    try:
        return environment.from_string(template_text).render(
            template_data(target, clone_url)
        )
    except jinja2.TemplateError as error:
        raise RenderError(
            f"Cannot render template for {target.name}: {error}"
        ) from error


# ==============================================================================
# Content Plans
# ==============================================================================
#
# A content plan is the extra material a command hands to the repositories it
# acts on: whole directories, and single files placed at a chosen path. Every
# path in a plan may carry the placeholders of a repository name, so one command
# can hand each student or group a file that nobody else receives. That is what
# makes a file too large or too structured for the student list -- a KUBECONFIG,
# a dataset, an exam variant -- distributable at all.


class ContentFile(BaseModel):
    """One source file handed to a repository under a chosen path."""

    model_config = ConfigDict(frozen=True)

    source: str
    destination: str


class ContentPlan(BaseModel):
    """The directories and files a command writes into each repository."""

    model_config = ConfigDict(frozen=True)

    directories: tuple[str, ...] = ()
    files: tuple[ContentFile, ...] = ()

    @property
    def is_empty(self) -> bool:
        """Report whether this plan hands out anything at all."""
        return not self.directories and not self.files

    def describe(self) -> tuple[str, ...]:
        """Describe the plan for the header a command prints before it acts."""
        described = [f"directory '{directory}'" for directory in self.directories]
        described += [
            f"file '{content_file.source}' as '{content_file.destination}'"
            for content_file in self.files
        ]
        return tuple(described)


def path_placeholders(template: str, description: str) -> frozenset[str]:
    """Return the placeholders of a content path, rejecting names ghtt cannot fill.

    Content paths deliberately reuse the vocabulary of the repository name
    template instead of inventing a second one: a teacher who can name
    repositories can already name a per-student hand-out directory.
    """
    try:
        fields = [
            field for _, field, _, _ in Formatter().parse(template) if field is not None
        ]
    except ValueError as error:
        raise RenderError(f"Invalid {description} {template!r}: {error}") from error

    unknown = sorted(set(fields) - set(NAME_TEMPLATE_PLACEHOLDERS))
    if unknown:
        known = ", ".join("{" + name + "}" for name in NAME_TEMPLATE_PLACEHOLDERS)
        raise RenderError(
            f"Unknown placeholder(s) in {description} {template!r}: "
            f"{', '.join(unknown)}. Use {known}."
        )
    return frozenset(fields)


def parse_content_file(value: str) -> ContentFile:
    """Parse one ``SOURCE=DESTINATION`` mapping as typed on the command line.

    The last separator splits the two halves. A destination is a path the
    teacher chooses inside the repository, while a source is often named by
    whichever tool generated the file, so the source is the half more likely to
    contain the separator itself.
    """
    source, separator, destination = value.rpartition(CONTENT_FILE_SEPARATOR)
    if not separator or not source or not destination:
        example = (
            f"kubeconfigs/{{student_group}}.yaml{CONTENT_FILE_SEPARATOR}.kube/config"
        )
        raise RenderError(
            f"Invalid --content-file {value!r}. Write it as "
            f"SOURCE{CONTENT_FILE_SEPARATOR}DESTINATION, for example {example!r}."
        )

    destination_path = Path(destination)
    if destination_path.is_absolute() or ".." in destination_path.parts:
        raise RenderError(
            f"Invalid destination {destination!r} in --content-file {value!r}: "
            "a destination is a path inside the repository, so it cannot be "
            "absolute or leave the repository."
        )

    path_placeholders(source, "content file source")
    path_placeholders(destination, "content file destination")
    return ContentFile(source=source, destination=destination_path.as_posix())


def build_content_plan(
    directories: list[str] | None, files: list[str] | None
) -> ContentPlan:
    """Turn the repeated --content-dir and --content-file options into one plan."""
    for directory in directories or ():
        path_placeholders(directory, "content directory")
    return ContentPlan(
        directories=tuple(directories or ()),
        files=tuple(parse_content_file(value) for value in files or ()),
    )


def validate_content_plan(plan: ContentPlan) -> None:
    """Check everything about a plan that does not depend on a single target.

    A path without placeholders is the same for every repository, so a mistake
    in it is a mistake about the whole run: it stops the command before any
    repository is touched instead of failing once per student.
    """
    for directory in plan.directories:
        if path_placeholders(directory, "content directory"):
            continue
        path = Path(directory)
        if not path.is_dir():
            raise RenderError(f"Content directory not found: {path}")
        if not any(entry.is_file() for entry in path.rglob("*")):
            raise RenderError(f"Content directory {path} holds no files")

    for content_file in plan.files:
        if path_placeholders(content_file.source, "content file source"):
            continue
        path = Path(content_file.source)
        if not path.is_file():
            raise RenderError(f"Content file not found: {path}")


def render_content_path(template: str, target: RepositoryTarget) -> Path:
    """Resolve one content path for a single repository target."""
    placeholders = path_placeholders(template, "content path")
    values: dict[str, str] = {}
    if "organization" in placeholders:
        values["organization"] = target.organization
    if "student_group" in placeholders:
        if target.group is None:
            raise RenderError(
                f"{template!r} uses {{student_group}}, but {target.name} is an "
                "individual repository and has no group."
            )
        values["student_group"] = target.group
    if "student_username" in placeholders:
        # A group repository holds several students, so no single username can
        # stand for it. Naming the placeholder that does is more useful than
        # handing one student's file to their whole group.
        if target.group is not None or len(target.students) != 1:
            raise RenderError(
                f"{template!r} uses {{student_username}}, but {target.name} is a "
                "group repository. Use {student_group} for group work."
            )
        values["student_username"] = target.students[0].username

    # A value carrying a path separator would silently move the hand-out
    # elsewhere in the filesystem, so it is refused rather than sanitized.
    for name, value in values.items():
        if not value or "/" in value or "\\" in value or value in {".", ".."}:
            raise RenderError(
                f"Cannot use the {name} {value!r} of {target.name} as part of "
                f"{template!r}: it is empty or contains a path separator."
            )
    return Path(template.format(**values))


class ContentSource(BaseModel):
    """One resolved file of a content plan and the path it lands on."""

    model_config = ConfigDict(frozen=True)

    path: Path
    destination: str


def content_sources(
    plan: ContentPlan, target: RepositoryTarget
) -> tuple[ContentSource, ...]:
    """Resolve every file one target receives, in the order they will be written.

    Directories come first and mapped files last, so an explicit
    ``--content-file`` can replace a path that a shared directory laid down.
    """
    sources: list[ContentSource] = []
    for directory in plan.directories:
        path = render_content_path(directory, target)
        if not path.is_dir():
            raise RenderError(f"Content directory not found: {path}")
        for entry in sorted(path.rglob("*")):
            if entry.is_dir():
                continue
            relative = entry.relative_to(path)
            # Git's own data is never course content, even inside a content
            # directory that happens to sit in a repository.
            if ".git" in relative.parts:
                continue
            if entry.suffix == TEMPLATE_SUFFIX:
                relative = relative.with_suffix("")
            sources.append(ContentSource(path=entry, destination=relative.as_posix()))

    for content_file in plan.files:
        path = render_content_path(content_file.source, target)
        if not path.is_file():
            raise RenderError(f"Content file not found: {path}")
        destination = render_content_path(content_file.destination, target)
        sources.append(ContentSource(path=path, destination=destination.as_posix()))

    if not sources:
        raise RenderError(f"The content to hand out holds no files for {target.name}")
    return tuple(sources)


class ContentChange(BaseModel):
    """One file a content plan writes into a repository."""

    model_config = ConfigDict(frozen=True)

    path: str
    replaced: bool

    def describe(self) -> str:
        """Mark a replaced file differently from a new one, at a glance."""
        return f"{'~' if self.replaced else '+'} {self.path}"


def write_content(
    plan: ContentPlan,
    destination: Path,
    target: RepositoryTarget,
    clone_url: str,
) -> tuple[ContentChange, ...]:
    """Write everything a content plan hands to one target into a working copy.

    A directory keeps its own layout, so ``content/docs/task.md`` lands at
    ``docs/task.md`` and replaces whatever was there; a mapped file lands at the
    destination it was given. A ``.jinja`` file is rendered for this target and
    loses that suffix; anything else is copied byte for byte, so images,
    archives, and generated credentials survive intact.
    """
    changes: list[ContentChange] = []
    for source in content_sources(plan, target):
        if source.path.suffix == TEMPLATE_SUFFIX:
            try:
                template_text = source.path.read_text(encoding="utf-8")
            except OSError as error:
                raise RenderError(
                    f"Cannot read template {source.path}: {error}"
                ) from error
            payload = render_text(template_text, target, clone_url).encode("utf-8")
        else:
            try:
                payload = source.path.read_bytes()
            except OSError as error:
                raise RenderError(f"Cannot read {source.path}: {error}") from error

        written = destination / source.destination
        replaced = written.exists()
        try:
            written.parent.mkdir(parents=True, exist_ok=True)
            written.write_bytes(payload)
        except OSError as error:
            raise RenderError(f"Cannot write {written}: {error}") from error
        changes.append(ContentChange(path=source.destination, replaced=replaced))
    return tuple(changes)


def render_tree(
    directory: Path, target: RepositoryTarget, clone_url: str
) -> tuple[Path, ...]:
    """Render every ``.jinja`` file in a working copy and drop the suffix.

    The caller is responsible for passing a throwaway copy of the source: each
    rendered file replaces its own template, which must never happen inside the
    teacher's own source repository.
    """
    rendered: list[Path] = []
    for template_path in sorted(directory.rglob(f"*{TEMPLATE_SUFFIX}")):
        # A template stored inside .git is Git's own data, not course content.
        if ".git" in template_path.relative_to(directory).parts:
            continue
        try:
            template_text = template_path.read_text(encoding="utf-8")
        except OSError as error:
            raise RenderError(
                f"Cannot read template {template_path}: {error}"
            ) from error

        output = render_text(template_text, target, clone_url)
        destination = template_path.with_suffix("")
        try:
            destination.write_text(output, encoding="utf-8")
            template_path.unlink()
        except OSError as error:
            raise RenderError(
                f"Cannot write rendered file {destination}: {error}"
            ) from error
        rendered.append(destination)
    return tuple(rendered)
