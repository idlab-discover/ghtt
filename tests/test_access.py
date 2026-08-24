"""Granting and removing access is idempotent and survives a missing student."""

from __future__ import annotations

import pytest

from ghtt.access import grant_access, remove_access

from .factories import make_context, make_settings, make_target
from .fake_github import FakeInvitation, FakeRepository

# ==============================================================================
# grant
# ==============================================================================


def test_grant_gives_push_access_by_default() -> None:
    repository = FakeRepository("course-team-1")
    context = make_context(
        (make_target("course-team-1", students=("ada", "bert")),), (repository,)
    )

    report = grant_access(context, read_only=False, assume_yes=True)

    assert repository.collaborators == {"ada": "push", "bert": "push"}
    assert report.processed == ("course-team-1",)
    assert report.failed == ()


def test_grant_read_only_gives_pull_access() -> None:
    repository = FakeRepository("course-team-1")
    context = make_context(
        (make_target("course-team-1", students=("ada",)),), (repository,)
    )

    grant_access(context, read_only=True, assume_yes=True)

    assert repository.collaborators == {"ada": "pull"}


def test_grant_skips_a_student_without_a_github_account() -> None:
    repository = FakeRepository("course-team-1")
    context = make_context(
        (make_target("course-team-1", students=("ada", "unknown-person")),),
        (repository,),
    )

    report = grant_access(context, read_only=False, assume_yes=True)

    assert repository.collaborators == {"ada": "push"}
    assert report.processed == ("course-team-1",)
    assert report.failed == ()


def test_grant_fails_the_target_when_the_repository_is_absent() -> None:
    context = make_context((make_target("course-team-1", students=("ada",)),), ())

    report = grant_access(context, read_only=False, assume_yes=True)

    assert report.processed == ()
    assert "does not exist" in report.failed[0]


def test_grant_dry_run_changes_nothing() -> None:
    repository = FakeRepository("course-team-1")
    context = make_context(
        (make_target("course-team-1", students=("ada",)),),
        (repository,),
        settings=make_settings(dry_run=True),
    )

    grant_access(context, read_only=False, assume_yes=False)

    assert repository.collaborators == {}
    assert repository.request_count == 0


def test_grant_reuses_the_single_organization_listing() -> None:
    repositories = tuple(
        FakeRepository(f"course-team-{index}") for index in range(1, 4)
    )
    targets = tuple(
        make_target(f"course-team-{index}", students=("ada",)) for index in range(1, 4)
    )
    context = make_context(targets, repositories)

    grant_access(context, read_only=False, assume_yes=True)

    # One collaborator call per student and no repository re-fetch anywhere.
    assert [repository.request_count for repository in repositories] == [1, 1, 1]


# ==============================================================================
# remove-grant
# ==============================================================================


def test_remove_grant_cancels_invitations_before_removing_collaborators() -> None:
    repository = FakeRepository("course-team-1")
    repository.invitations = [FakeInvitation("ada", 7), FakeInvitation("cy", 8)]
    repository.collaborators = {"ada": "push", "cy": "push"}
    context = make_context(
        (make_target("course-team-1", students=("ada",)),), (repository,)
    )

    report = remove_access(context, assume_yes=True)

    assert [invitation.id for invitation in repository.invitations] == [8]
    assert repository.collaborators == {"cy": "push"}
    assert repository.removed_collaborators == ["ada"]
    assert report.processed == ("course-team-1",)


def test_remove_grant_is_idempotent_without_invitation_or_collaborator() -> None:
    repository = FakeRepository("course-team-1")
    context = make_context(
        (make_target("course-team-1", students=("ada",)),), (repository,)
    )

    report = remove_access(context, assume_yes=True)

    assert report.processed == ("course-team-1",)
    assert report.failed == ()


def test_remove_grant_dry_run_changes_nothing() -> None:
    repository = FakeRepository("course-team-1")
    repository.invitations = [FakeInvitation("ada", 7)]
    repository.collaborators = {"ada": "push"}
    context = make_context(
        (make_target("course-team-1", students=("ada",)),),
        (repository,),
        settings=make_settings(dry_run=True),
    )

    remove_access(context, assume_yes=False)

    assert repository.collaborators == {"ada": "push"}
    assert [invitation.id for invitation in repository.invitations] == [7]


@pytest.mark.parametrize("read_only", [False, True])
def test_grant_reports_the_permission_it_used(read_only: bool) -> None:
    repository = FakeRepository("course-team-1")
    context = make_context(
        (make_target("course-team-1", students=("ada",)),), (repository,)
    )

    grant_access(context, read_only=read_only, assume_yes=True)

    assert repository.collaborators["ada"] == ("pull" if read_only else "push")
