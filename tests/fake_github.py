"""Deterministic stand-ins for the PyGithub objects that ghtt actually uses.

The fakes record every mutation so a test can assert what ghtt asked GitHub to
do, and they count requests so a test can prove a command does not re-fetch data
it already has. No test in this suite contacts GitHub.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from github import GithubException


class FakeAuthor:
    def __init__(self, name: str, email: str) -> None:
        self.name = name
        self.email = email


class FakeCommitDetail:
    def __init__(self, author: FakeAuthor) -> None:
        self.author = author


class FakeCommit:
    def __init__(self, author_name: str, author_email: str) -> None:
        self.commit = FakeCommitDetail(FakeAuthor(author_name, author_email))


class FakeBranch:
    def __init__(self, name: str, commit: FakeCommit) -> None:
        self.name = name
        self.commit = commit
        self.protection: dict[str, Any] | None = None

    def edit_protection(self, **arguments: Any) -> None:
        self.protection = arguments


class FakeRepository:
    def __init__(
        self,
        name: str,
        organization: str = "course",
        default_branch: str = "master",
        author: tuple[str, str] = ("Ada Lovelace", "ada@example.edu"),
    ) -> None:
        self.name = name
        self.full_name = f"{organization}/{name}"
        self.html_url = f"https://github.example.edu/{organization}/{name}"
        self.clone_url = f"https://github.example.edu/{organization}/{name}.git"
        self.ssh_url = f"git@github.example.edu:{organization}/{name}.git"
        self.default_branch = default_branch
        self.description: str | None = None
        self.deleted = False
        self.local_path: Path | None = None
        self.branches = {
            default_branch: FakeBranch(default_branch, FakeCommit(*author))
        }
        self.collaborators: dict[str, str] = {}
        self.removed_collaborators: list[str] = []
        self.invitations: list[FakeInvitation] = []
        self.milestones: list[FakeMilestone] = []
        self.issues: list[FakeIssue] = []
        self.pulls: list[FakePullRequest] = []
        self.edits: list[dict[str, Any]] = []
        self.request_count = 0

    def back_with_local_repository(self, path: Path) -> None:
        """Point the clone URLs at a real bare repository that Git can push to."""
        from .local_git import make_bare_repository

        make_bare_repository(path)
        self.local_path = path
        self.clone_url = str(path)
        self.ssh_url = str(path)

    # --- reads -------------------------------------------------------------

    def get_branch(self, name: str) -> FakeBranch:
        self.request_count += 1
        if name not in self.branches:
            raise GithubException(404, "Branch not found", {})
        return self.branches[name]

    def get_pending_invitations(self) -> list[FakeInvitation]:
        self.request_count += 1
        return list(self.invitations)

    def get_milestones(self, state: str = "open") -> list[FakeMilestone]:
        self.request_count += 1
        return [m for m in self.milestones if state == "all" or m.state == state]

    def get_issues(self, state: str = "open") -> list[FakeIssue]:
        self.request_count += 1
        return [i for i in self.issues if state == "all" or i.state == state]

    def get_pulls(self, state: str = "open", **_: Any) -> list[FakePullRequest]:
        self.request_count += 1
        return [p for p in self.pulls if state == "all" or p.state == state]

    # --- writes ------------------------------------------------------------

    def edit(self, **arguments: Any) -> None:
        self.request_count += 1
        self.edits.append(arguments)
        if "description" in arguments:
            self.description = arguments["description"]
        if "name" in arguments:
            self.name = arguments["name"]

    def delete(self) -> None:
        self.request_count += 1
        self.deleted = True

    def add_to_collaborators(self, username: str, permission: str) -> None:
        self.request_count += 1
        if username.startswith("unknown"):
            raise GithubException(404, "Not Found", {})
        self.collaborators[username] = permission

    def remove_from_collaborators(self, username: str) -> None:
        self.request_count += 1
        self.collaborators.pop(username, None)
        self.removed_collaborators.append(username)

    def remove_invitation(self, invite_id: int) -> None:
        self.request_count += 1
        self.invitations = [i for i in self.invitations if i.id != invite_id]

    def create_milestone(
        self, title: str, description: Any = None, due_on: Any = None
    ) -> FakeMilestone:
        self.request_count += 1
        milestone = FakeMilestone(title, description, due_on, len(self.milestones) + 1)
        self.milestones.append(milestone)
        return milestone

    def create_issue(
        self,
        title: str,
        body: Any = None,
        milestone: Any = None,
        labels: Any = None,
        assignees: Any = None,
    ) -> FakeIssue:
        self.request_count += 1
        wanted = list(assignees or [])
        # GitHub refuses the whole issue when an assignee cannot be assigned.
        if any(login.startswith("unknown") for login in wanted):
            raise GithubException(422, "Validation Failed", {})
        issue = FakeIssue(title, body, milestone, list(labels or []), wanted)
        self.issues.append(issue)
        return issue

    def create_pull(
        self, title: str, body: str, base: str, head: str
    ) -> FakePullRequest:
        self.request_count += 1
        pull = FakePullRequest(title, body, base, head, len(self.pulls) + 1, self)
        self.pulls.append(pull)
        return pull


class FakeInvitation:
    """A pending invitation. PyGithub exposes `id` and a NamedUser `invitee`."""

    def __init__(self, invitee: str, id: int) -> None:
        self.invitee = FakeUser(invitee)
        self.id = id


class FakeMilestone:
    def __init__(self, title: str, description: Any, due_on: Any, number: int) -> None:
        self.title = title
        self.description = description
        self.due_on = due_on
        self.number = number
        self.state = "open"
        self.edits: list[dict[str, Any]] = []

    def edit(self, **arguments: Any) -> None:
        self.edits.append(arguments)
        self.title = arguments.get("title", self.title)
        self.description = arguments.get("description", self.description)
        self.due_on = arguments.get("due_on", self.due_on)


class FakeLabel:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeUser:
    def __init__(self, login: str) -> None:
        self.login = login


class FakeIssue:
    def __init__(
        self,
        title: str,
        body: Any,
        milestone: Any,
        labels: list[str],
        assignees: list[str],
    ) -> None:
        self.title = title
        self.body = body
        self.milestone = milestone
        self.labels = [FakeLabel(label) for label in labels]
        self.assignees = [FakeUser(login) for login in assignees]
        self.state = "open"
        self.edits: list[dict[str, Any]] = []

    def edit(self, **arguments: Any) -> None:
        self.edits.append(arguments)


class FakePullRequest:
    def __init__(
        self,
        title: str,
        body: str,
        base: str,
        head: str,
        number: int,
        repository: FakeRepository,
    ) -> None:
        self.title = title
        self.body = body
        self.base = FakeBranchReference(base)
        self.head = FakeBranchReference(head)
        self.number = number
        self.state = "open"
        self.html_url = f"{repository.html_url}/pull/{number}"


class FakeBranchReference:
    def __init__(self, ref: str) -> None:
        self.ref = ref


class FakeOrganization:
    def __init__(
        self,
        login: str,
        repositories: list[FakeRepository] | None = None,
        local_root: Path | None = None,
    ) -> None:
        self.login = login
        self.html_url = f"https://github.example.edu/{login}"
        self.repositories = list(repositories or [])
        self.listings = 0
        self.created: list[dict[str, Any]] = []
        # When a test sets local_root, a created repository is backed by a real
        # bare repository on disk so a push can be inspected afterwards.
        self.local_root = local_root

    def get_repos(self, type: str = "all") -> list[FakeRepository]:
        self.listings += 1
        return list(self.repositories)

    def create_repo(self, name: str, **arguments: Any) -> FakeRepository:
        self.created.append({"name": name, **arguments})
        repository = FakeRepository(name, organization=self.login)
        if self.local_root is not None:
            repository.back_with_local_repository(self.local_root / name)
        self.repositories.append(repository)
        return repository


class FakeSearchResult:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository


class FakeGithub:
    def __init__(
        self,
        organization: FakeOrganization | None = None,
        search_results: list[FakeSearchResult] | None = None,
    ) -> None:
        self.organization = organization
        self.search_results = list(search_results or [])
        self.searches = 0

    def get_organization(self, login: str) -> FakeOrganization:
        if self.organization is None or self.organization.login != login:
            raise GithubException(404, "Not Found", {})
        return self.organization

    def search_code(self, query: str) -> list[FakeSearchResult]:
        self.searches += 1
        return list(self.search_results)
