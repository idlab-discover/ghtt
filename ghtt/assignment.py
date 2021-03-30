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
from github.GithubException import UnknownObjectException
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
    '--branch-already-pushed', '-B',
    help="Branch has already been pushed, so this doesn't need to be done anymore.",
    is_flag=True)
@click.option(
    '--students',
    help='Comma-separated list of usernames. Defaults to all students.')
@click.option(
    '--groups',
    help='Comma-separated list of group names. Defaults to all groups.')
def create_pr(ctx, branch, title, body, source, students=None, groups=None, branch_already_pushed=False):
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

    for repo in repos.values():
        try:
            g_repo = g_org.get_repo(repo.name)
        except UnknownObjectException:
            click.secho("Warning: repository {}/{} not found, skipping".format(g_org.html_url, repo.name), fg="red")
            continue
        if not branch_already_pushed:
            command = ["git", "push", g_repo.ssh_url, "master:{}".format(branch)]
            cwd = source
            print("\nwill run `{}`\nin directory `{}`.".format(command, cwd))
            if click.confirm('Do you want to continue?'):
                if not branch_already_pushed:
                    subprocess.check_call(command, cwd=cwd)
                pr = g_repo.create_pull(title, "master", branch, body=body)
                click.secho("created pull request {}".format(pr.html_url))
        else:
            click.secho("Creating pull request in {}".format(repo.name), fg="green")
            pr = g_repo.create_pull(title=title, body=body, base="master", head=branch)
            click.secho("created pull request {}".format(pr.html_url))


def generate_file_from_template(path, clone_url, repo: ghtt.config.StudentRepo):
    """generate_file_from_template fills in the provided jinja2 template. If the filename ends with
    `.jinja`, the template file is removed and the result is saved without that extension. If not,
    the template file is overwritten with the generated result.
    """
    print("TEMPLATE: ", open(path).read())
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
    )

#%%
# template = open("/home/merlijn/PHD/SYSPROG/project/sysprog-2020-opgave-code-studenten/README.md.jinja").read()


#%%

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
def create_repos(ctx, source, students=None, groups=None):
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

    for repo in repos.values():
        # if len(repo.students) != 2:
        #     continue

        try:
            g_repo = g_org.create_repo(repo.name, private=True)
            click.secho("\n\nGenerating repo {}/{}".format(g_org.html_url, repo.name), fg="green")
        except github.GithubException:
            click.secho("WARNING: Repository {}/{} already exists; skipping..".format(g_org.html_url, repo.name), fg="red")
            continue

        subprocess.check_call(["git", "checkout", "master"], cwd=source)
        subprocess.call(["git", "branch", "-D", repo.name], cwd=source)
        subprocess.check_call(["git", "checkout", "-b", repo.name], cwd=source)


        from pathlib import Path

        for path in Path(source).rglob('*.jinja'):
            generate_file_from_template(
                path,
                clone_url=g_repo.clone_url,
                repo=repo)
        subprocess.check_call(["git", "add", "-A"], cwd=source)
        subprocess.call(["git", "commit", "-m", "fill in templates"], cwd=source)
        click.secho("Pushing source to {}".format(g_repo.ssh_url), fg="green")
        subprocess.check_call(["git", "push", g_repo.ssh_url, "{}:master".format(repo.name)], cwd=source)
        subprocess.check_call(["git", "checkout", "master"], cwd=source)
        
        click.secho("Protecting the master branch so students can't rewrite history", fg="green")
        g_repo = g_org.get_repo(repo.name)
        g_master = g_repo.get_branch("master")
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
def create_issues(ctx, path, students=None, groups=None):
    """Create issues in the repositories of the specified users and groups.
    """
    if students:
        students = [s.strip() for s in students.split(",")]
    if groups:
        groups = [gr.strip() for gr in groups.split(",")]

    click.secho("# Creating issues defined in {}...".format(path), fg="green")

    with open(path) as f:
        issue_templates: Optional[List[Dict]] = yaml.safe_load(f)
    assert issue_templates is not None
    assert isinstance(issue_templates, list)
    assert len(issue_templates) > 0
    assert isinstance(issue_templates[0], dict)

    g: github.Github = ctx.obj['pyg']
    g_org = g.get_organization(ghtt.config.get_organization())

    students = ghtt.config.get_students(usernames=students, groups=groups)
    mentors = ghtt.config.get_mentors()
    repos = ghtt.config.get_repos(students, mentors=mentors)

    for repo in repos.values():
        click.secho("\n\nGenerating issues in repo {}/{}".format(g_org.html_url, repo.name), fg="green")

        try:
            g_repo = g_org.get_repo(repo.name)
        except UnknownObjectException:
            click.secho("Warning: repository {}/{} not found, skipping".format(g_org.html_url, repo.name), fg="red")
            continue

        for issue_template in issue_templates:
            issue_type = issue_template.get('type')

            if issue_type == 'milestone':
                try:
                    g_repo.create_milestone(
                        title=render_template(issue_template.get('title'), g_repo.ssh_url, repo),
                        description=issue_template.get('description'),
                        due_on=issue_template.get('due date')
                    )
                except github.GithubException as e:
                    if len(e.data["errors"]) != 1  or e.data["errors"][0]["code"] != "already_exists":
                        raise

                    

            elif issue_type == 'issue':
                click.secho("Adding issue with title '{}'".format(issue_template.get('title')), fg="green")

                # find the milestone, if any
                milestone = issue_template.get('milestone', github.GithubObject.NotSet)
                if milestone is not github.GithubObject.NotSet:
                    milestone = [ms for ms in g_repo.get_milestones() if ms.title == milestone][0]

                g_repo.create_issue(
                    title=render_template(issue_template.get('title'), g_repo.ssh_url, repo),
                    body=render_template(issue_template.get('body'), g_repo.ssh_url, repo),
                    milestone=milestone,
                    labels=issue_template.get('labels', []),
                    assignees=[
                        render_template(a, g_repo.ssh_url, repo) for a in issue_template.get('assignees', [])
                    ]
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
def pull(ctx, source, students=None, groups=None):
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
    repos = ghtt.config.get_repos(students)

    summary = []

    try:
        for repo in repos.values():
            try:
                g_repo = g_org.get_repo(repo.name)

                subprocess.check_call(
                    ["git", "fetch", g_repo.ssh_url, "master:{}".format(g_repo.name)], cwd=source)

                # subprocess.check_call(["git", "checkout", g_repo.name], cwd=source)
                timestamp = subprocess.check_output(["git", "log", g_repo.name, "-1", "--pretty=format:%ct"], cwd=source, universal_newlines=True).rstrip()
                commit_summary = subprocess.check_output(["git", "log", g_repo.name, "-1", "--pretty=format:%s"], cwd=source, universal_newlines=True)
                committer = subprocess.check_output(["git", "log", g_repo.name, "-1", "--pretty=format:%an <%ae>"], cwd=source, universal_newlines=True)

                commit_time = datetime.fromtimestamp(int(timestamp))
                summary.append((g_repo.name, g_repo.description, commit_time, committer, commit_summary))
            except UnknownObjectException:
                summary.append((repo.name, repo.comment, datetime.now(), None, "pull failed: repository not found"))
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
def grant(ctx, students=None, groups=None):
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
    for student in students:
        print(student.username, student.group)

    repos = ghtt.config.get_repos(students)



    for repo in repos.values():
        try:
            g_repo = g_org.get_repo(repo.name)
        except UnknownObjectException:
            click.secho("Warning: repository {}/{} not found, skipping".format(g_org.html_url, repo.name), fg="red")
            continue
        click.secho("Adding the student as collaborator", fg="green")
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
def remove_grant(ctx, students=None, groups=None):
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
    repos = ghtt.config.get_repos(students)

    for repo in repos.values():
        try:
            g_repo = g_org.get_repo(repo.name)
        except UnknownObjectException:
            click.secho("Warning: repository {}/{} not found, skipping".format(g_org.html_url, repo.name), fg="red")
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
