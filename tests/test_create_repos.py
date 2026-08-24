"""create-repos seeds real repositories without ever touching the source."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ghtt.config import Config, RepositoryConfig
from ghtt.errors import GhttError
from ghtt.repositories import (
    BranchProtectionError,
    create_repositories,
    validate_protected_branches,
)
from ghtt.settings import Settings
from ghtt.templates import ContentFile, ContentPlan

from .factories import (
    make_context,
    make_settings,
    make_target,
    recorded_organization,
)
from .fake_github import FakeRepository
from .local_git import branches_of, commit_count, file_in_branch, git, make_repository


def make_source(tmp_path: Path, template: str | None = None) -> Path:
    """Create a source repository, optionally with one .jinja template in it."""
    source = make_repository(tmp_path / "template")
    if template is not None:
        (source / "README.md.jinja").write_text(template, encoding="utf-8")
        git(source, "add", "-A")
        git(source, "commit", "-m", "add template")
    return source


def settings_for(source: Path, repos: RepositoryConfig | None = None) -> Settings:
    return make_settings(
        Config(
            source=source,
            default_branch="master",
            repos=repos or RepositoryConfig(),
        )
    )


# ==============================================================================
# Creating and seeding
# ==============================================================================


def test_create_repos_pushes_the_source_and_configures_the_repository(
    tmp_path: Path,
) -> None:
    source = make_source(tmp_path)
    context = make_context(
        (make_target("course-team-1", students=("ada", "bert"), group="team-1"),),
        settings=settings_for(source, RepositoryConfig(has_issues=True)),
        local_root=tmp_path / "remote",
    )

    report = create_repositories(context, assume_yes=True, content=ContentPlan())

    organization = recorded_organization(context)
    created = organization.repositories[0]
    assert organization.created[0]["private"] is True
    assert organization.created[0]["has_issues"] is True
    assert created.local_path is not None
    assert branches_of(created.local_path) == ["master"]
    assert created.edits == [{"default_branch": "master", "description": "Ada, Bert"}]
    assert created.branches["master"].protection == {}
    assert report.processed == ("course-team-1",)


def test_templates_are_rendered_per_repository_and_the_source_is_untouched(
    tmp_path: Path,
) -> None:
    source = make_source(tmp_path, "Clone {{ repo.name }} from {{ clone_url }}.\n")
    before_branches = branches_of(source)
    before_commits = commit_count(source, "master")
    context = make_context(
        (make_target("course-team-1", students=("ada",), group="team-1"),),
        settings=settings_for(source),
        local_root=tmp_path / "remote",
    )

    create_repositories(context, assume_yes=True, content=ContentPlan())

    created = recorded_organization(context).repositories[0]
    assert created.local_path is not None
    rendered = file_in_branch(created.local_path, "master", "README.md")
    assert "Clone course-team-1 from" in rendered
    # The template file itself is replaced by its rendered output.
    with pytest.raises(subprocess.CalledProcessError):
        file_in_branch(created.local_path, "master", "README.md.jinja")
    # Nothing was added to the teacher's own repository.
    assert branches_of(source) == before_branches
    assert commit_count(source, "master") == before_commits
    assert (source / "README.md.jinja").exists()


def test_require_pull_requests_is_applied_to_the_protected_branch(
    tmp_path: Path,
) -> None:
    source = make_source(tmp_path)
    context = make_context(
        (make_target("course-team-1", students=("ada",)),),
        settings=settings_for(source, RepositoryConfig(require_pull_requests=True)),
        local_root=tmp_path / "remote",
    )

    create_repositories(context, assume_yes=True, content=ContentPlan())

    created = recorded_organization(context).repositories[0]
    assert created.branches["master"].protection == {
        "required_approving_review_count": 0
    }


# ==============================================================================
# Safety
# ==============================================================================


def test_an_existing_repository_is_skipped_and_never_overwritten(
    tmp_path: Path,
) -> None:
    source = make_source(tmp_path)
    existing = FakeRepository("course-team-1")
    context = make_context(
        (make_target("course-team-1", students=("ada",)),),
        (existing,),
        settings=settings_for(source),
        local_root=tmp_path / "remote",
    )

    report = create_repositories(context, assume_yes=True, content=ContentPlan())

    assert recorded_organization(context).created == []
    assert existing.edits == []
    assert report.skipped == ("course-team-1",)
    assert report.failed == ()


def test_a_source_without_the_default_branch_names_the_setting(tmp_path: Path) -> None:
    source = make_repository(tmp_path / "template", default_branch="main")
    context = make_context(
        (make_target("course-team-1", students=("ada",)),),
        settings=settings_for(source),
        local_root=tmp_path / "remote",
    )

    with pytest.raises(GhttError, match="default-branch: main"):
        create_repositories(context, assume_yes=True, content=ContentPlan())

    assert recorded_organization(context).created == []


def test_a_source_that_is_not_a_repository_is_rejected(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    context = make_context(
        (make_target("course-team-1", students=("ada",)),),
        settings=settings_for(plain),
    )

    with pytest.raises(GhttError, match="not a Git repository"):
        create_repositories(context, assume_yes=True, content=ContentPlan())


def test_a_wildcard_protection_pattern_is_refused_up_front() -> None:
    with pytest.raises(BranchProtectionError, match="rulesets"):
        validate_protected_branches(("release/*",))


def test_an_extra_branch_that_does_not_exist_is_reported_not_ignored(
    tmp_path: Path,
) -> None:
    source = make_source(tmp_path)
    context = make_context(
        (make_target("course-team-1", students=("ada",)),),
        settings=settings_for(
            source, RepositoryConfig(protect_branches=("solutions",))
        ),
        local_root=tmp_path / "remote",
    )

    report = create_repositories(context, assume_yes=True, content=ContentPlan())

    assert report.processed == ()
    assert "could not protect solutions" in report.failed[0]


def test_dry_run_creates_nothing(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    settings = make_settings(
        Config(source=source, default_branch="master"), dry_run=True
    )
    context = make_context(
        (make_target("course-team-1", students=("ada",)),),
        settings=settings,
        local_root=tmp_path / "remote",
    )

    report = create_repositories(context, assume_yes=False, content=ContentPlan())

    assert recorded_organization(context).created == []
    assert report.skipped == ("course-team-1",)


# ==============================================================================
# Per-repository content
# ==============================================================================


def kubeconfig_plan(root: Path) -> ContentPlan:
    """Hand each group its own directory plus its own generated file."""
    return ContentPlan(
        directories=(str(root / "handouts" / "{student_group}"),),
        files=(
            ContentFile(
                source=str(root / "kubeconfigs" / "{student_group}.yaml"),
                destination=".kube/config",
            ),
        ),
    )


def generate_content(root: Path, group: str) -> None:
    directory = root / "handouts" / group
    directory.mkdir(parents=True)
    (directory / "cluster.md").write_text(f"Cluster of {group}.\n", encoding="utf-8")
    (root / "kubeconfigs").mkdir(exist_ok=True)
    (root / "kubeconfigs" / f"{group}.yaml").write_text(
        f"cluster: {group}\n", encoding="utf-8"
    )


def test_content_is_in_the_repository_from_its_first_day(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    generate_content(tmp_path, "team-1")
    context = make_context(
        (make_target("course-team-1", students=("ada",), group="team-1"),),
        settings=settings_for(source),
        local_root=tmp_path / "remote",
    )

    report = create_repositories(
        context, assume_yes=True, content=kubeconfig_plan(tmp_path)
    )

    assert report.processed == ("course-team-1",)
    created = recorded_organization(context).repositories[0]
    assert created.local_path is not None
    assert file_in_branch(created.local_path, "master", "cluster.md") == (
        "Cluster of team-1.\n"
    )
    assert file_in_branch(created.local_path, "master", ".kube/config") == (
        "cluster: team-1\n"
    )
    # The hand-out is its own commit on top of the assignment source.
    assert (
        git(created.local_path, "log", "-1", "--pretty=%s", "master").strip()
        == "add per-repository content"
    )


def test_a_group_without_content_fails_without_stopping_the_course(
    tmp_path: Path,
) -> None:
    source = make_source(tmp_path)
    # The generator ran for one group only.
    generate_content(tmp_path, "team-1")
    context = make_context(
        (
            make_target("course-team-1", students=("ada",), group="team-1"),
            make_target("course-team-2", students=("bert",), group="team-2"),
        ),
        settings=settings_for(source),
        local_root=tmp_path / "remote",
    )

    report = create_repositories(
        context, assume_yes=True, content=kubeconfig_plan(tmp_path)
    )

    assert report.processed == ("course-team-1",)
    assert report.failed[0].startswith("course-team-2: Content directory not found")


def test_a_shared_content_mistake_stops_before_any_repository_is_created(
    tmp_path: Path,
) -> None:
    source = make_source(tmp_path)
    context = make_context(
        (make_target("course-team-1", students=("ada",), group="team-1"),),
        settings=settings_for(source),
        local_root=tmp_path / "remote",
    )

    with pytest.raises(GhttError, match="Content directory not found"):
        create_repositories(
            context,
            assume_yes=True,
            content=ContentPlan(directories=(str(tmp_path / "handouts"),)),
        )

    assert recorded_organization(context).created == []


def test_a_dry_run_rehearses_the_content_of_every_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = make_source(tmp_path)
    generate_content(tmp_path, "team-1")
    settings = make_settings(
        Config(source=source, default_branch="master"), dry_run=True
    )
    context = make_context(
        (
            make_target("course-team-1", students=("ada",), group="team-1"),
            make_target("course-team-2", students=("bert",), group="team-2"),
        ),
        settings=settings,
        local_root=tmp_path / "remote",
    )

    report = create_repositories(
        context, assume_yes=True, content=kubeconfig_plan(tmp_path)
    )

    printed = capsys.readouterr()
    assert "would add cluster.md" in printed.out
    assert "would add .kube/config" in printed.out
    # A group whose file was never generated is named now, not halfway through.
    assert "no content for course-team-2" in printed.err
    assert report.skipped == ("course-team-1",)
    assert report.failed[0].startswith("course-team-2: Content directory not found")
    assert recorded_organization(context).created == []
