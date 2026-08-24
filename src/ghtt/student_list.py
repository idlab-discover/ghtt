"""Read student lists and derive individual or group repository targets."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from string import Formatter

from jinja2 import Environment, StrictUndefined, TemplateError
from pydantic import BaseModel, ConfigDict

from .config import Config, StudentListConfig
from .defaults import (
    GROUP_NAME_TEMPLATE,
    INDIVIDUAL_NAME_TEMPLATE,
    NAME_TEMPLATE_PLACEHOLDERS,
)
from .errors import GhttError

# ==============================================================================
# Derived Domain Values
# ==============================================================================


class StudentListError(GhttError):
    """Student-list data cannot safely be used to choose repository targets."""


class Person(BaseModel):
    """One validated row from a student or mentor list."""

    # Commands plan with people but do not modify the imported list data.
    model_config = ConfigDict(frozen=True)

    username: str
    comment: str
    groups: tuple[str, ...]
    record: dict[str, str]


class RepositoryTarget(BaseModel):
    """The people and metadata that define one generated repository."""

    # A target is the reviewed plan for later GitHub work, so it stays stable
    # after target derivation and confirmation.
    model_config = ConfigDict(frozen=True)

    name: str
    organization: str
    group: str | None
    students: tuple[Person, ...]
    mentors: tuple[Person, ...]
    url: str = ""

    @property
    def description(self) -> str:
        """Keep descriptions stable so plans and updates do not churn unnecessarily."""
        return ", ".join(person.comment for person in self.students if person.comment)

    @property
    def comment(self) -> str:
        """Expose the legacy name that existing ``.jinja`` templates still use."""
        return self.description


# ==============================================================================
# Input Normalization
# ==============================================================================


def normalize_group(group: str) -> str:
    """Normalize human-entered group labels before comparison or repository naming."""
    return re.sub(r"[^0-9a-z]+", "-", group.lower()).strip("-")


def parse_filter(value: str | None, option: str) -> frozenset[str] | None:
    """Parse a comma-separated filter and reject ambiguous empty selections."""
    if value is None:
        return None

    values = frozenset(part.strip() for part in value.split(",") if part.strip())
    if not values:
        raise StudentListError(f"{option} must contain at least one value")
    return values


# ==============================================================================
# CSV Import
# ==============================================================================


def load_student_list(student_list: StudentListConfig, role: str) -> tuple[Person, ...]:
    """Load one student or mentor list before target derivation begins."""
    try:
        with student_list.source.open(newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames is None:
                raise StudentListError(
                    f"{role} list {student_list.source} is missing a header row"
                )

            # Check field names once. Row processing can then use configured
            # columns directly and report row-specific data problems clearly.
            mapping = student_list.field_mapping
            for field in (mapping.username, mapping.group, mapping.groups):
                if field is not None and field not in reader.fieldnames:
                    raise StudentListError(
                        f"{role} list {student_list.source} is missing "
                        f"configured column {field!r}"
                    )

            # Strict rendering catches a typo in a comment template before it
            # becomes a misleading repository description.
            environment = Environment(undefined=StrictUndefined)
            people: list[Person] = []
            for row_number, row in enumerate(reader, start=2):
                if row.get(None) or any(value is None for value in row.values()):
                    raise StudentListError(
                        f"Malformed row {row_number} in {role} list "
                        f"{student_list.source}"
                    )

                record: dict[str, str] = {}
                for column, value in row.items():
                    if column is not None and isinstance(value, str):
                        record[column] = value

                # Legacy exports sometimes prefix usernames with '#'. Remove
                # exactly that marker while retaining every other character.
                username = record[mapping.username].removeprefix("#").strip()
                if not username:
                    raise StudentListError(
                        f"Empty value for {mapping.username!r} at row {row_number} "
                        f"in {role} list {student_list.source}"
                    )

                if mapping.group is not None:
                    group_values = (record[mapping.group],)
                elif mapping.groups is not None:
                    group_values = record[mapping.groups].split(",")
                else:
                    group_values = ()

                # A person appears once per repository even if their CSV cell
                # repeats a group under different punctuation or capitalization.
                normalized_groups = {
                    normalize_group(group)
                    for group in group_values
                    if normalize_group(group)
                }
                groups = tuple(sorted(normalized_groups))
                try:
                    comment = environment.from_string(mapping.comment).render(
                        record=record
                    )
                except TemplateError as error:
                    raise StudentListError(
                        f"Invalid comment template at row {row_number} "
                        f"in {role} list {student_list.source}: {error}"
                    ) from error
                people.append(
                    Person(
                        username=username,
                        comment=comment,
                        groups=groups,
                        record=record,
                    )
                )
    except FileNotFoundError as error:
        raise StudentListError(
            f"{role} list file not found: {student_list.source}"
        ) from error
    except OSError as error:
        raise StudentListError(
            f"Cannot read {role} list {student_list.source}: {error}"
        ) from error

    return tuple(sorted(people, key=lambda person: person.username))


# ==============================================================================
# Repository Planning
# ==============================================================================


def build_targets(
    config: Config,
    organization: str,
    students: Iterable[Person],
    mentors: Iterable[Person] = (),
    student_filter: frozenset[str] | None = None,
    group_filter: frozenset[str] | None = None,
    repo_name_template: str | None = None,
    github_url: str = "",
) -> tuple[RepositoryTarget, ...]:
    """Build full repositories first, then apply all supplied filter categories."""
    # Stable sorting makes plans, confirmations, and later command output
    # reproducible even when CSV row order changes.
    students = tuple(sorted(students, key=lambda person: person.username))
    mentors = tuple(sorted(mentors, key=lambda person: person.username))

    # A configured group column changes the unit of work from one person to one
    # group. The Config model already rejects using both group column styles.
    grouped = config.students is not None and (
        config.students.field_mapping.group is not None
        or config.students.field_mapping.groups is not None
    )
    template = repo_name_template or config.repos.name_template
    if template is None:
        template = GROUP_NAME_TEMPLATE if grouped else INDIVIDUAL_NAME_TEMPLATE

    # Validate the template before creating targets. Its values are also the
    # complete compatibility contract for documented legacy placeholders.
    template_values = dict.fromkeys(NAME_TEMPLATE_PLACEHOLDERS, "")
    template_values["organization"] = organization
    try:
        fields = [
            field for _, field, _, _ in Formatter().parse(template) if field is not None
        ]
    except ValueError as error:
        raise StudentListError(
            f"Invalid repository name template {template!r}: {error}"
        ) from error
    unknown = sorted(set(fields) - template_values.keys())
    if unknown:
        raise StudentListError(
            f"Unknown repository name placeholder(s): {', '.join(unknown)}"
        )

    # Build complete repositories before filtering. Selecting one person in a
    # group identifies their repository; it must not remove their teammates.
    def repository_url(name: str) -> str:
        return f"{github_url}/{organization}/{name}" if github_url else name

    targets: list[RepositoryTarget] = []
    if grouped:
        groups = sorted({group for student in students for group in student.groups})
        for group in groups:
            name = template.format(**(template_values | {"student_group": group}))
            targets.append(
                RepositoryTarget(
                    name=name,
                    organization=organization,
                    group=group,
                    students=tuple(
                        student for student in students if group in student.groups
                    ),
                    # A mentor guides the groups their own list names, so an
                    # individual repository below never receives one.
                    mentors=tuple(
                        mentor for mentor in mentors if group in mentor.groups
                    ),
                    url=repository_url(name),
                )
            )
    else:
        for student in students:
            name = template.format(
                **(template_values | {"student_username": student.username})
            )
            targets.append(
                RepositoryTarget(
                    name=name,
                    organization=organization,
                    group=None,
                    students=(student,),
                    mentors=(),
                    url=repository_url(name),
                )
            )

    # Reject the entire plan before any API call if its names would be unsafe.
    # This prevents a later target from silently overwriting or sharing a repo.
    seen_names: set[str] = set()
    duplicate_names: set[str] = set()
    for target in targets:
        if not target.name:
            raise StudentListError("Repository name template produces an empty name")
        if target.name in seen_names:
            duplicate_names.add(target.name)
        seen_names.add(target.name)
    if duplicate_names:
        raise StudentListError(
            "Repository name template produces duplicate names: "
            f"{', '.join(sorted(duplicate_names))}"
        )

    # Both filter categories narrow the plan. A target must satisfy every
    # supplied category, which is why the checks are combined with ``and``.
    normalized_groups = (
        frozenset(normalize_group(group) for group in group_filter)
        if group_filter is not None
        else None
    )
    selected_targets: list[RepositoryTarget] = []
    for target in targets:
        has_selected_student = student_filter is None or any(
            student.username in student_filter for student in target.students
        )
        has_selected_group = (
            normalized_groups is None or target.group in normalized_groups
        )
        if has_selected_student and has_selected_group:
            selected_targets.append(target)
    return tuple(selected_targets)
