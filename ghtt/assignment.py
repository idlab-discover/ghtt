#!/usr/bin/env python3

from functools import wraps
import os
import subprocess
from datetime import datetime
from typing import Optional, List, Dict, Union

import click
import requests
import yaml
from github import Repository
from tabulate import tabulate
import jinja2
import github

from .auth import needs_auth
import ghtt.config

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
    '--students',
    help='Comma-separated list of usernames. Defaults to all students.',
    required="False")
@click.option(
    '--groups',
    help='Comma-separated list of group names. Defaults to all groups.',
    required="False")
def create_pr(ctx, branch, title, body, source, students=None, groups=None):
    """Pushes updated code to a new branch on students repositories and creates a pr to merge that
    branch into master.
    """
    click.secho("# Branch: '{}'".format(branch), fg="green")
    click.secho("# title: '{}'".format(title), fg="green")
    click.secho("# message: '{}'".format(body), fg="green")
    click.secho("# source directory: '{}'".format(source), fg="green")
    click.secho("# Creating update pr..", fg="green")

    click.confirm(
        'Please check if the above information is correct.\nDo you want to continue?', abort=True)

    if students:
        students = students.split(",")
    if groups:
        groups = groups.split(",")

    click.secho("# Creating student repositories..", fg="green")
    click.secho("# Source: '{}'".format(source), fg="green")

    g : github.Github = ctx.obj['pyg']
    g_org = g.get_organization(ghtt.config.get_organization())

    students = ghtt.config.get_students(usernames=students, groups=groups)
    repos = ghtt.config.get_repos(students)

    for repo in repos:
        g_repo = g_org.get_repo(repo.name)
        command = ["git", "push", g_repo.ssh_url, "master:{}".format(branch)]
        cwd = source
        print("\nwill run `{}`\nin directory `{}`.".format(command, cwd))
        if click.confirm('Do you want to continue?'):
            subprocess.check_call(command, cwd=cwd)
            pr = g_repo.create_pull(title, "master", branch, body=body)
            click.secho("created pull request {}".format(pr.html_url))


def get_reponame(username, organization):
    return "{}-{}".format(organization.lower(), username.lower())

# def get_reponame(username, organization):
#     return "examen-{}".format(username.lower())


def generate_from_template(path, clone_url, repo_name):
    """generate_from_template fills in the provided jinja2 template. If the filename ends with
    `.jinja`, the template file is removed and the result is saved without that extension. If not,
    the template file is overwritten with the generated result.
    """
    template = jinja2.Template(open(path).read())
    outputText = template.render(
        clone_url=clone_url,
        repo_name=repo_name,
    )
    destination = path
    if destination.endswith('.jinja'):
        os.remove(path)
        destination = destination[:-6]
    with open(destination, "w+") as d_file:
        d_file.write(outputText)


@assignment.command()
@click.pass_context
@click.option(
    '--source',
    help='path to repo with start code',
    default=lambda: ghtt.config.get('source', None))
@click.option(
    '--students',
    help='Comma-separated list of usernames. Defaults to all students.',
    required="False")
@click.option(
    '--groups',
    help='Comma-separated list of group names. Defaults to all groups.',
    required="False")
def create_repos(ctx, source, students=None, groups=None):
    """Create student repositories in the organization specified by the url.
    Each repository will contain a copy of the specified source and will have force-pushing disabled
    so students can not rewrite history.

    Note: this command does not grant students access to those repositories. See `assignment grant`.
    """
    if students:
        students = students.split(",")
    if groups:
        groups = groups.split(",")

    click.secho("# Creating student repositories..", fg="green")
    click.secho("# Source: '{}'".format(source), fg="green")

    g : github.Github = ctx.obj['pyg']
    g_org = g.get_organization(ghtt.config.get_organization())

    students = ghtt.config.get_students(usernames=students, groups=groups)
    repos = ghtt.config.get_repos(students)

    for repo in repos.values():
        click.secho("\n\nGenerating repo {}".format(repo.name), fg="green")

        try:
            g_repo = g_org.create_repo(repo.name, private=True)
        except github.GithubException:
            g_repo = g_org.get_repo(repo.name)

        subprocess.check_call(["git", "checkout", "master"], cwd=source)
        subprocess.call(["git", "branch", "-D", repo.name], cwd=source)
        subprocess.check_call(["git", "checkout", "-b", repo.name], cwd=source)

        if os.path.isfile("{}/README.md.jinja".format(source)):
            generate_from_template(
                "{}/README.md.jinja".format(source),
                clone_url=g_repo.clone_url,
                repo_name=g_repo.name)
        subprocess.check_call(["git", "add", "-A"], cwd=source)
        subprocess.call(["git", "commit", "-m", "fill in templates"], cwd=source)
        click.secho("Pushing source to {}".format(g_repo.ssh_url), fg="green")
        subprocess.check_call(["git", "push", g_repo.ssh_url, "{}:master".format(repo.name)], cwd=source)
        subprocess.check_call(["git", "checkout", "master"], cwd=source)
        
        click.secho("Protecting the master branch so students can't rewrite history", fg="green")
        g_repo = g.get_repo("{}/{}".format(repo.organization, g_repo.name))
        g_master = g_repo.get_branch("master")
        g_master.edit_protection()

        click.secho("Adding comment to repo", fg="green")
        g_repo.edit(description=repo.comment)


def to_strlist_helper(str_or_list: Union[str, List[str], None]) -> List[str]:
    if str_or_list is None:
        return []
    elif isinstance(str_or_list, str):
        return [str_or_list]
    else:
        assert isinstance(str_or_list, list)
        return str_or_list


def use_jinja(target: str, stud_repo: ghtt.config.StudentRepo, g_repo: Repository) -> str:
    template = jinja2.Template(target)
    mentor = [m for m in stud_repo.mentors if m == stud_repo.students[0].mentor_username][0]

    return template.render(
        clone_url=g_repo.clone_url,
        repo_name=g_repo.repo_name,
        student1_fullname=stud_repo.students[0].fullname,  # TODO
        student1_username=stud_repo.students[0].username,
        student2_fullname=stud_repo.students[0].fullname,  # TODO
        student2_username=stud_repo.students[0].username,
        mentor_username=mentor.username,
        mentor_fullname=mentor.fullname,  # TODO
        mentor_email=mentor.email,  # TODO
    )



@assignment.command()
@click.pass_context
@click.option(
    '--issuefile',
    help='path to yml file describing issues to be created',
    required=True)
@click.option(
    '--students',
    help='Comma-separated list of usernames. Defaults to all students.',
    required="False")
@click.option(
    '--groups',
    help='Comma-separated list of group names. Defaults to all groups.',
    required="False")
def create_issues(ctx, source, issuefile, students=None, groups=None):
    """Create student repositories in the organization specified by the url.
    Each repository will contain a copy of the specified source and will have force-pushing disabled
    so students can not rewrite history.

    Note: this command does not grant students access to those repositories. See `assignment grant`.
    """
    if students:
        students = students.split(",")
    if groups:
        groups = groups.split(",")

    click.secho("# Creating issues defined in {}...".format(issuefile), fg="green")
    click.secho("# Source: '{}'".format(source), fg="green")

    with open(issuefile) as f:
        issues_commands: Optional[List[Dict]] = yaml.safe_load(f).get('add')
    assert issues_commands is not None
    assert isinstance(issues_commands, list)
    assert len(issues_commands) > 0
    assert isinstance(issues_commands[0], dict)

    g: github.Github = ctx.obj['pyg']
    g_org = g.get_organization(ghtt.config.get_organization())

    students = ghtt.config.get_students(usernames=students, groups=groups)
    mentors = ghtt.config.get_mentors()
    repos = ghtt.config.get_repos(students, mentors)

    for repo in repos.values():
        click.secho("\n\nGenerating issues in repo {}".format(repo.name), fg="green")

        g_repo = g_org.get_repo(repo.name)

        #Saw the below in other code, but why would this be needed? Why doesn't g_repo work?
        # g_repo = g.get_repo("{}/{}".format(repo.organization, g_repo.name))
        # g_master = g_repo.get_branch("master")

        for issues_command in issues_commands:
            command_type = issues_command.get('type')

            if command_type == 'milestone':
                g_repo.create_milestone(
                    title=issues_command.get('title'),
                    description=issues_command.get('description'),
                    due_on=issues_command.get('due_on')
                )
            elif command_type == 'issue':
                click.secho("Adding issue with title \"{}\"".format(issues_command.get('title')), fg="green")

                # find the milestone, if any
                milestone = issues_command.get('milestone', default=None)
                if milestone is not None:
                    milestone = [ms for ms in g_repo.get_milestones() if ms.title == milestone][0]

                g_repo.create_issue(
                    title=issues_command.get('title'),
                    body=issues_command.get('body'),
                    milestone=milestone,
                    labels=to_strlist_helper(issues_command.get('labels')),
                    assignees=to_strlist_helper(issues_command.get('assignees'))
                )


@assignment.command()
@click.pass_context
@click.option(
    '--source',
    help='path to repo with start code',
    default=lambda: ghtt.config.get('source', None))
@click.option(
    '--students',
    help='Comma-separated list of usernames. Defaults to all students.',
    required="False")
@click.option(
    '--groups',
    help='Comma-separated list of group names. Defaults to all groups.',
    required="False")
def pull(ctx, source, students=None, groups=None):
    """Show the latest commit of each student
    """
    if students:
        students = students.split(",")
    if groups:
        groups = groups.split(",")

    click.secho("# Showing the latest commit..", fg="green")
    click.secho("# Path: '{}'".format(source), fg="green")
    click.secho("# Students: '{}'".format(students), fg="green")

    g : github.Github = ctx.obj['pyg']
    g_org = g.get_organization(ghtt.config.get_organization())
    
    students = ghtt.config.get_students(usernames=students, groups=groups)
    repos = ghtt.config.get_repos(students)

    summary = []

    try:
        for repo in repos.values():
            g_repo = g_org.get_repo(repo.name)

            subprocess.check_call(["git", "checkout", repo.name], cwd=source)
            subprocess.check_call(
                ["git", "pull", g_repo.ssh_url, "master:{}".format(repo.name)], cwd=source)

            timestamp = subprocess.check_output(["git", "log", "-1", "--pretty=format:%ct"], cwd=source, universal_newlines=True).rstrip()
            commit_summary = subprocess.check_output(["git", "log", "-1", "--pretty=format:%s"], cwd=source, universal_newlines=True)
            committer = subprocess.check_output(["git", "log", "-1", "--pretty=format:%an <%ae>"], cwd=source, universal_newlines=True)

            commit_time = datetime.fromtimestamp(int(timestamp))
            summary.append((repo.name, repo.comment, commit_time, committer, commit_summary))
    finally:
        subprocess.check_call(["git", "checkout", "master"], cwd=source)
        summary.sort(key=lambda tup: tup[2])
        click.secho(tabulate(summary, headers=['Username', "Description", 'Last commit time', "Committer info", 'Commit summary']))


@assignment.command()
@click.pass_context
@click.option(
    '--students',
    help='list of students',
    required="False")
@click.option(
    '--groups',
    help='Comma-separated list of group names. Defaults to all groups.',
    required="False")
def grant(ctx, students=None, groups=None):
    """Grant each student push access (the collaborator role) to their repository in the
    organization specified by the url.
    """
    if students:
        students = students.split(",")
    if groups:
        groups = groups.split(",")

    click.secho("# Granting students write permission to their repository..", fg="green")
    click.secho("# Students: '{}'".format(students), fg="green")

    g : github.Github = ctx.obj['pyg']
    g_org = g.get_organization(ghtt.config.get_organization())
    
    students = ghtt.config.get_students(usernames=students, groups=groups)
    repos = ghtt.config.get_repos(students)

    for repo in repos.values():
        g_repo = g_org.get_repo(repo.name)
        click.secho("Adding the student as collaborator", fg="green")
        for student in students:
            g_repo.add_to_collaborators(student.username)


@assignment.command()
@click.pass_context
@click.option(
    '--students',
    help='list of students',
    required="False")
@click.option(
    '--groups',
    help='Comma-separated list of group names. Defaults to all groups.',
    required="False")
def remove_grant(ctx, students=None, groups=None):
    """Removes students' push access to their repository and cancels any open invitation for that
    student.
    """
    if students:
        students = students.split(",")
    if groups:
        groups = groups.split(",")

    click.secho("# Removing students write permission to their repository..", fg="green")
    click.secho("# Students: '{}'".format(students), fg="green")

    g : github.Github = ctx.obj['pyg']
    g_org = g.get_organization(ghtt.config.get_organization())
    
    students = ghtt.config.get_students(usernames=students, groups=groups)
    repos = ghtt.config.get_repos(students)

    for repo in repos.values():
        g_repo = g_org.get_repo(repo.name)
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
