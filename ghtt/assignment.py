#!/usr/bin/env python3

from functools import wraps
import os
import subprocess
from datetime import datetime, date, timezone
from typing import Optional, List, Dict, Union

import click
import requests
import yaml
from github import Repository
from github.GithubException import UnknownObjectException
from tabulate import tabulate
import jinja2
import github
from pathlib import Path

from .auth import needs_auth
import ghtt.config
from ghtt.config import StudentRepo


class AbortGhtt(Exception):
    pass


class ProceedAsker:
    def __init__(self, yes: bool, action: str):
        self.auto_mode = "all" if yes else None
        self.action = action

    def should_proceed(self, subject: str) -> bool:
        assert(self.auto_mode in ["all", "none", None])
        if self.auto_mode == "all":
            return True
        elif self.auto_mode == "none":
            return False

        user_choice = click.prompt(f'Do you want to {self.action} "{subject}"?',
                                   default=None, show_choices=True,
                                   type=click.Choice(['y', 'all', 'n', 'none', 'abort'], case_sensitive=False))
        if user_choice == 'y':
            return True
        elif user_choice == 'all':
            self.auto_mode = "all"
            return True
        elif user_choice == 'n':
            click.secho('Skipping {}'.format(subject), fg="yellow")
            return False
        elif user_choice == 'none':
            self.auto_mode = 'none'
            return False
        elif user_choice == 'abort':
            click.secho('Aborting!', fg="red")
            raise AbortGhtt()
        else:
            assert False, f'Unknown choice {user_choice!r}'  # should not occur


def _check_repo_groups(yes: bool, repos: Dict[str, StudentRepo]) -> Dict[str, StudentRepo]:
    # Check if all repo's have expected number of students/mentors
    ok_repos = {}
    expected_group_size = ghtt.config.get('expected-group-size', 1)
    expected_mentor_count = ghtt.config.get('expected-mentors-per-group', 0)

    asker = ProceedAsker(yes=False, action='proceed with invalid group')

    for repname, repo in repos.items():
        if (
                (expected_group_size and len(repo.students) != expected_group_size)
                or (expected_mentor_count and len(repo.mentors) != expected_mentor_count)
        ):
            if expected_mentor_count or repo.mentors:
                click.secho("Group {} has {} students and {} mentors (expected {}/{}):"
                            .format(repo.group, len(repo.students), len(repo.mentors),
                                    expected_group_size, expected_mentor_count))
            else:
                click.secho("Group {} has {} students (expected {}):"
                            .format(repo.group, len(repo.students), expected_group_size))
            for stud in repo.students:
                click.secho('   - student {} ({})'.format(stud.username, stud.comment))
            for ment in repo.mentors:
                click.secho('   - mentor {} ({})'.format(ment.username, ment.comment))

            if asker.should_proceed(repo.group):
                ok_repos[repname] = repo
        else:
            ok_repos[repname] = repo

    return ok_repos


@click.group()
@needs_auth
@click.pass_context
def assignment(ctx):
    pass


@assignment.command()
@click.pass_context
@click.option(
    '--branch',
    help='Name of the branch to create in students repos',
    required="True")
@click.option(
    '--title',
    help='Title of the pull request.',
    required="True")
@click.option(
    '--body',
    help='Body of the pull request (the message).',
    required="True")
@click.option(
    '--source', '-s',
    help='Source directory',
    default=lambda: ghtt.config.get('source', None))
@click.option(
    '--branch-already-pushed', '-B',
    help="Branch has already been pushed, so this doesn't need to be done anymore.",
    is_flag=True)
@click.option(
    '--students',
    help='Comma-separated list of usernames. Defaults to all students.')
@click.option(
    '--groups',
    help='Comma-separated list of group names. Defaults to all groups.')
@click.option(
    '--yes',
    help='Process all students/groups, without confirmation.', is_flag=True)
def create_pr(ctx, branch, title, body, source, yes, students=None, groups=None, branch_already_pushed=False):
    """Pushes updated code to a new branch on students repositories and creates a pr to merge that
    branch into master.
    """
    click.secho("# Branch: '{}'".format(branch), fg="green")
    click.secho("# title: '{}'".format(title), fg="green")
    click.secho("# message: '{}'".format(body), fg="green")
    if not branch_already_pushed:
        click.secho("# source directory: '{}'".format(source), fg="green")
    else:
        click.secho("# Branch has been pushed already.", fg="green")
    click.secho("# Creating update pr..", fg="green")

    click.confirm(
        'Please check if the above information is correct.\nDo you want to continue?', abort=True)

    if students:
        students = [s.strip() for s in students.split(",")]
    if groups:
        groups = [gr.strip() for gr in groups.split(",")]

    click.secho("# Creating pull request in student repositories..", fg="green")

    g: github.Github = ctx.obj['pyg']
    g_org = g.get_organization(ghtt.config.get_organization())

    students = ghtt.config.get_students(usernames=students, groups=groups)
    mentors = ghtt.config.get_mentors()
    repos = ghtt.config.get_repos(students, mentors=mentors)
    repos = _check_repo_groups(yes=yes, repos=repos)

    asker = ProceedAsker(yes=yes, action='create the PR for')

    default_branch = ghtt.config.get('default-branch', 'master')

    for repo in repos.values():
        try:
            g_repo = g_org.get_repo(repo.name)
        except UnknownObjectException:
            click.secho("Warning: repository {} not found, skipping".format(repo.url), fg="yellow")
            continue
        if not asker.should_proceed(repo.url):
            continue

        if not branch_already_pushed:
            command = ["git", "push", g_repo.ssh_url, f"{default_branch}:{branch}"]
            cwd = source
            click.secho("\nwill run `{}`\nin directory `{}`.".format(command, cwd))

            subprocess.check_call(command, cwd=cwd)
            pr = g_repo.create_pull(title=title, body=body, base=default_branch, head=branch)
            click.secho("created pull request {}".format(pr.html_url))
        else:
            click.secho("Creating pull request in {}".format(repo.name), fg="green")
            pr = g_repo.create_pull(title=title, body=body, base=default_branch, head=branch)
            click.secho("created pull request {}".format(pr.html_url))


def generate_file_from_template(path, clone_url, repo: ghtt.config.StudentRepo):
    """generate_file_from_template fills in the provided jinja2 template. If the filename ends with
    `.jinja`, the template file is removed and the result is saved without that extension. If not,
    the template file is overwritten with the generated result.
    """
    try:
        template = open(path).read()
        outputText = render_template(template, clone_url, repo)
        destination = str(path)
        if destination.endswith('.jinja'):
            os.remove(path)
            destination = destination[:-6]
        with open(destination, "w+") as d_file:
            d_file.write(outputText)
    except:
        click.secho(f'Problem generating template for path={path} clone_url={clone_url}', fg='red')
        raise


def render_template(template: str, clone_url, repo: ghtt.config.StudentRepo) -> str:
    template = jinja2.Template(template)
    return template.render(
        clone_url=clone_url,
        group=repo.group,
        students=repo.students,
        mentors=repo.mentors,
        repo=repo,
    )


@assignment.command()
@click.pass_context
@click.option(
    '--source',
    help='path to repo with start code',
    default=lambda: ghtt.config.get('source', None))
@click.option(
    '--students',
    help='Comma-separated list of usernames. Defaults to all students.')
@click.option(
    '--groups',
    help='Comma-separated list of group names. Defaults to all groups.')
@click.option(
    '--yes',
    help='Process all students/groups, without confirmation.', is_flag=True)
def create_repos(ctx, source, yes, students=None, groups=None):
    """Create student repositories in the organization specified by the url.
    Each repository will contain a copy of the specified source and will have force-pushing disabled
    so students can not rewrite history.

    Note: this command does not grant students access to those repositories. See `assignment grant`.
    """
    if students:
        students = [s.strip() for s in students.split(",")]
    if groups:
        groups = [gr.strip() for gr in groups.split(",")]

    click.secho("# Creating student repositories..", fg="green")
    click.secho("# Source: '{}'".format(source), fg="green")

    g : github.Github = ctx.obj['pyg']
    g_org = g.get_organization(ghtt.config.get_organization())

    students = ghtt.config.get_students(usernames=students, groups=groups)
    mentors = ghtt.config.get_mentors()
    repos = ghtt.config.get_repos(students, mentors=mentors)
    repos = _check_repo_groups(yes=yes, repos=repos)

    asker = ProceedAsker(yes=yes, action='create the repo')

    for repo in repos.values():
        try:
            g_repo = g_org.get_repo(repo.name)
            click.secho("Warning: repository {}/{} already exists; skipping..".format(g_org.html_url, repo.name), fg="yellow")
            continue
        except UnknownObjectException:
            pass
        if not asker.should_proceed(repo.url):
            continue

        g_repo = g_org.create_repo(
            repo.name, private=True,
            has_issues=ghtt.config.get('repos.has-issues', False),
            has_wiki=ghtt.config.get('repos.has-wiki', False),
            has_downloads=False,
            has_projects=False,
        )

        # dangerous because we use methods with _
        default_branch = ghtt.config.get('default-branch', 'master')
        g_repo.edit(default_branch=default_branch)

        click.secho("\n\nGenerating repo {}/{}".format(g_org.html_url, repo.name), fg="green")

        try:
            subprocess.check_call(["git", "checkout", default_branch], cwd=source)
        except subprocess.CalledProcessError:
            click.secho(f"The branch `{default_branch}` does not exist in the source repository. Please specify the correct source branch in `ghtt.yaml` using the `default-branch` keyword.")
            raise
        subprocess.call(["git", "branch", "-D", repo.name], cwd=source)
        subprocess.check_call(["git", "checkout", "-b", repo.name], cwd=source)

        for path in Path(source).rglob('*.jinja'):
            generate_file_from_template(
                path,
                clone_url=g_repo.clone_url,
                repo=repo)
        subprocess.check_call(["git", "add", "-A"], cwd=source)
        subprocess.call(["git", "commit", "-m", "fill in templates"], cwd=source)
        click.secho("Pushing source to {}".format(g_repo.ssh_url), fg="green")
        subprocess.check_call(["git", "push", g_repo.ssh_url, f"{repo.name}:{default_branch}"], cwd=source)
        subprocess.check_call(["git", "checkout", default_branch], cwd=source)  # go back to source branch

        click.secho(f"Protecting the {default_branch} branch so students can't rewrite history", fg="green")
        g_repo = g_org.get_repo(repo.name)
        g_master = g_repo.get_branch(default_branch)
        g_master.edit_protection()

        click.secho("Adding comment to repo", fg="green")
        g_repo.edit(description=repo.comment)


@assignment.command()
@click.pass_context
@click.argument(
    "path",
    required=True)
@click.option(
    "--students",
    help="Comma-separated list of usernames. Defaults to all students.")
@click.option(
    "--groups",
    help="Comma-separated list of group names. Defaults to all groups.")
@click.option(
    '--yes',
    help='Process all students/groups, without confirmation.', is_flag=True)
def create_issues(ctx, path, yes, students=None, groups=None):
    """Create issues in the repositories of the specified users and groups.
    """
    if students:
        students = [s.strip() for s in students.split(",")]
    if groups:
        groups = [gr.strip() for gr in groups.split(",")]

    click.secho("# Creating issues defined in {}...".format(path), fg="green")

    g: github.Github = ctx.obj['pyg']
    g_org = g.get_organization(ghtt.config.get_organization())

    students = ghtt.config.get_students(usernames=students, groups=groups)
    mentors = ghtt.config.get_mentors()
    repos = ghtt.config.get_repos(students, mentors=mentors)
    repos = _check_repo_groups(yes=yes, repos=repos)

    asker = ProceedAsker(yes=yes, action='create the issue(s) for')

    with open(path) as f:
        issue_template_content = f.read()

    for repo in repos.values():
        try:
            g_repo = g_org.get_repo(repo.name)
        except UnknownObjectException:
            click.secho("Warning: repository {} not found, skipping".format(repo.url), fg="yellow")
            continue
        if not asker.should_proceed(repo.url):
            continue

        click.secho("Generating issues in repo {}/{}".format(g_org.html_url, repo.name), fg="green")

        issue_dicts: Optional[List[Dict]] = yaml.safe_load(render_template(issue_template_content, g_repo.ssh_url, repo))
        assert issue_dicts is not None
        assert isinstance(issue_dicts, list)
        assert len(issue_dicts) > 0
        assert isinstance(issue_dicts[0], dict)

        for issue_dict in issue_dicts:
            issue_type = issue_dict.get('type')

            if issue_type == 'milestone':
                # convert due_on to datetime
                due_on = issue_dict.get('due date')
                if isinstance(due_on, str):
                    from dateutil import parser
                    due_on = parser.parse(due_on)
                elif isinstance(due_on, date):
                    due_on = datetime.combine(due_on, datetime.min.time())
                assert isinstance(due_on, datetime)
                # prevent evil naive datetime
                if due_on.tzinfo is None or due_on.tzinfo.utcoffset(due_on) is None:
                    from dateutil.tz import tz
                    due_on = due_on.replace(tzinfo=tz.tzlocal()).astimezone(tz.tzlocal())
                    assert due_on.tzinfo is not None and due_on.tzinfo.utcoffset(due_on) is not None

                # find existing milestone with same title
                matching_milestone = [existing_milestone for existing_milestone in g_repo.get_milestones()
                                      if existing_milestone.title == issue_dict.get('title')]
                if len(matching_milestone) == 1:
                    if issue_dict.get('title') == matching_milestone[0].title and \
                       issue_dict.get('description') == matching_milestone[0].description and \
                        due_on == matching_milestone[0].due_on.replace(tzinfo=timezone.utc):
                        click.secho("Skipping up to date milestone '{}'".format(issue_dict.get('title')), fg="green")
                    else:
                        click.secho("Updating milestone '{}'".format(issue_dict.get('title')), fg="green")
                        matching_milestone[0].edit(
                            title=issue_dict.get('title'),
                            description=issue_dict.get('description'),
                            due_on=due_on,
                        )
                elif len(matching_milestone) == 0:
                    click.secho("Adding milestone '{}'".format(issue_dict.get('title')), fg="green")
                    try:
                        g_repo.create_milestone(
                            title=issue_dict.get('title'),
                            description=issue_dict.get('description'),
                            due_on=due_on,
                        )
                    except github.GithubException as e:
                        if len(e.data["errors"]) != 1 or e.data["errors"][0]["code"] != "already_exists":
                            raise
                else:
                    # this is normally impossible
                    click.secho(f"Skipping: There already exist {len(matching_milestone)} milestones "
                                f"with title '{issue_dict.get('title')}'", fg="red")
            elif issue_type == 'issue':
                # find the milestone, if any
                milestone = issue_dict.get('milestone', github.GithubObject.NotSet)
                if milestone is not github.GithubObject.NotSet:
                    milestone = [ms for ms in g_repo.get_milestones() if ms.title == milestone][0]

                # find existing issue with same title
                matching_issue = [existing_issue for existing_issue in g_repo.get_issues()
                                  if existing_issue.title == issue_dict.get('title')]

                if len(matching_issue) == 1:
                    same_labels = issue_dict.get('labels', []).sort() == [l.name for l in matching_issue[0].labels].sort()
                    same_assignees = set(issue_dict.get('assignees')) == set([l.login for l in matching_issue[0].assignees])
                    same_milestone = (
                        issue_dict.get('milestone') == matching_issue[0].milestone or
                        matching_issue[0].milestone is not None and issue_dict.get('milestone') == matching_issue[0].milestone.title
                    )
                    if issue_dict.get('title') == matching_issue[0].title and \
                       issue_dict.get('body') == matching_issue[0].body and \
                       same_labels and \
                       same_assignees and \
                       same_milestone:
                        click.secho("Skipping up to date issue '{}'".format(issue_dict.get('title')), fg="green")
                    else:
                        click.secho("Updating issue with title '{}'".format(issue_dict.get('title')), fg="green")
                        matching_issue[0].edit(
                            title=issue_dict.get('title'),
                            body=issue_dict.get('body'),
                            milestone=milestone,
                            labels=issue_dict.get('labels', []),
                            assignees=issue_dict.get('assignees', []),
                            # state=xxx,
                        )
                elif len(matching_issue) == 0:
                    click.secho("Adding issue with title '{}'".format(issue_dict.get('title')), fg="green")
                    g_repo.create_issue(
                        title=issue_dict.get('title'),
                        body=issue_dict.get('body'),
                        milestone=milestone,
                        labels=issue_dict.get('labels', []),
                        assignees=issue_dict.get('assignees', []),
                    )
                else:
                    click.secho(f"Skipping: There already exist {len(matching_issue)} issues "
                                f"with title '{issue_dict.get('title')}'", fg="red")


@assignment.command()
@click.pass_context
@click.option(
    '--source',
    help='path to repo with start code',
    default=lambda: ghtt.config.get('source', None))
@click.option(
    '--students',
    help='Comma-separated list of usernames. Defaults to all students.')
@click.option(
    '--groups',
    help='Comma-separated list of group names. Defaults to all groups.')
@click.option(
    '--yes',
    help='Process all students/groups, without confirmation.', is_flag=True)
def pull(ctx, source, yes, students=None, groups=None):
    """Show the latest commit of each student
    """
    if students:
        students = [s.strip() for s in students.split(",")]
    if groups:
        groups = [gr.strip() for gr in groups.split(",")]

    click.secho("# Showing the latest commit..", fg="green")
    click.secho("# Path: '{}'".format(source), fg="green")
    click.secho("# Students: '{}'".format(students), fg="green")

    g : github.Github = ctx.obj['pyg']
    g_org = g.get_organization(ghtt.config.get_organization())

    students = ghtt.config.get_students(usernames=students, groups=groups)
    repos = ghtt.config.get_repos(students, mentors=ghtt.config.get_mentors())

    summary = []

    asker = ProceedAsker(yes=yes, action='pull')

    # Make sure master is checked out because we can't pull to checked out branch
    default_branch = ghtt.config.get('default-branch', 'master')
    subprocess.check_call(["git", "checkout", default_branch], cwd=source)

    try:
        for repo in repos.values():
            try:
                g_repo = g_org.get_repo(repo.name)
            except UnknownObjectException:
                summary.append((repo.name, repo.comment, datetime.now(), None, "pull failed: repository not found"))
                continue

            if not asker.should_proceed(repo.url):
                continue

            try:
                g_repo = g_org.get_repo(repo.name)

                subprocess.check_call(
                    ["git", "fetch", g_repo.ssh_url, "HEAD:{}".format(g_repo.name)], cwd=source)

                # subprocess.check_call(["git", "checkout", g_repo.name], cwd=source)
                timestamp = subprocess.check_output(["git", "log", g_repo.name, "-1", "--pretty=format:%ct"], cwd=source, universal_newlines=True).rstrip()
                commit_summary = subprocess.check_output(["git", "log", g_repo.name, "-1", "--pretty=format:%s"], cwd=source, universal_newlines=True)
                committer = subprocess.check_output(["git", "log", g_repo.name, "-1", "--pretty=format:%an <%ae>"], cwd=source, universal_newlines=True)

                commit_time = datetime.fromtimestamp(int(timestamp))
                summary.append((g_repo.name, g_repo.description, commit_time, committer, commit_summary))
            except subprocess.CalledProcessError:
                summary.append((g_repo.name, g_repo.description, datetime.now(), None, "pull failed; see output above"))
    finally:
        summary.sort(key=lambda tup: tup[2])
        click.secho(tabulate(summary, headers=['Username', "Description", 'Last commit time', "Committer info", 'Commit summary']))


@assignment.command()
@click.pass_context
@click.option(
    '--students',
    help='list of students')
@click.option(
    '--groups',
    help='Comma-separated list of group names. Defaults to all groups.')
@click.option(
    '--yes',
    help='Process all students/groups, without confirmation.', is_flag=True)
def grant(ctx, yes, students=None, groups=None):
    """Grant each student push access (the collaborator role) to their repository in the
    organization specified by the url.
    """
    if students:
        students = [s.strip() for s in students.split(",")]
    if groups:
        groups = [gr.strip() for gr in groups.split(",")]

    click.secho("# Granting students write permission to their repository..", fg="green")
    click.secho("# Students: '{}'".format(students), fg="green")

    g : github.Github = ctx.obj['pyg']
    g_org = g.get_organization(ghtt.config.get_organization())

    students = ghtt.config.get_students(usernames=students, groups=groups)
    repos = ghtt.config.get_repos(students, mentors=ghtt.config.get_mentors())

    asker = ProceedAsker(yes=yes, action='give students')

    for repo in repos.values():
        try:
            g_repo = g_org.get_repo(repo.name)
        except UnknownObjectException:
            click.secho("Warning: repository {} not found, skipping".format(repo.url), fg="yellow")
            continue
        if not asker.should_proceed('{}" access to "{}'.format('", "'.join([s.username for s in repo.students]), repo.url)):
            continue

        click.secho("Adding students {} as collaborators to {}".format([s.username for s in repo.students], repo.url), fg="green")
        for student in repo.students:
            g_repo.add_to_collaborators(student.username)


@assignment.command()
@click.pass_context
@click.option(
    '--students',
    help='list of students')
@click.option(
    '--groups',
    help='Comma-separated list of group names. Defaults to all groups.')
@click.option(
    '--yes',
    help='Process all students/groups, without confirmation.', is_flag=True)
def remove_grant(ctx, yes, students=None, groups=None):
    """Removes students' push access to their repository and cancels any open invitation for that
    student.
    """
    if students:
        students = [s.strip() for s in students.split(",")]
    if groups:
        groups = [gr.strip() for gr in groups.split(",")]

    click.secho("# Removing students write permission to their repository..", fg="green")
    click.secho("# Students: '{}'".format(students), fg="green")

    g : github.Github = ctx.obj['pyg']
    g_org = g.get_organization(ghtt.config.get_organization())

    students = ghtt.config.get_students(usernames=students, groups=groups)
    repos = ghtt.config.get_repos(students, mentors=ghtt.config.get_mentors())

    asker = ProceedAsker(yes=yes, action='remove grants from')

    for repo in repos.values():
        try:
            g_repo = g_org.get_repo(repo.name)
        except UnknownObjectException:
            click.secho("Warning: repository {} not found, skipping".format(repo.url), fg="yellow")
            continue
        if not asker.should_proceed(repo.url):
            continue

        # Delete open invitations for that user
        # Do this before removing as collaborator so we don't get a race condition where
        # student accepts invitation between the remove as collaborator and the remove
        # of the invitation.
        for invitation in g_repo.get_pending_invitations():
            if str(invitation.invitee) in [s.username for s in repo.students]:
                click.secho("Removing invitation for student '{}' for repo '{}'".format(
                    invitation.invitee, repo.name), fg="green")
                invitation.delete()
                g_repo.remove_invitation(invitation.invite_id)
        # Remove user from collaborators
        for username in [s.username for s in repo.students]:
            click.secho("Removing '{}' as collaborators from '{}'".format(
                username, repo.name), fg="green")
            g_repo.remove_from_collaborators(username)
