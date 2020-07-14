#!/usr/bin/env python3

from functools import wraps
import os
import subprocess
from urllib.parse import urlparse
from datetime import datetime

import click
import github3
import requests
from tabulate import tabulate
import jinja2
import github as pygithub

from .auth import needs_auth

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
    help='Source directory')
def create_pr(ctx, branch, title, body, source):
    """Pushes updated code to a new branch on students repositories and creates a pr to merge that
    branch into master.
    """
    organization = urlparse(ctx.obj['url']).path.rstrip("/").rsplit("/", 1)[-1]

    click.secho("# Organization: '{}'".format(organization), fg="green")
    click.secho("# Branch: '{}'".format(branch), fg="green")
    click.secho("# title: '{}'".format(title), fg="green")
    click.secho("# message: '{}'".format(body), fg="green")
    click.secho("# source directory: '{}'".format(source), fg="green")
    click.secho("# Creating update pr..", fg="green")

    click.confirm(
        'Please check if the above information is correct.\nDo you want to continue?', abort=True)

    g = ctx.obj['gh']

    org = g.organization(organization)

    for repo in org.repositories():
        command = ["git", "push", repo.ssh_url, "master:{}".format(branch)]
        cwd = source
        print("\nwill run `{}`\nin directory `{}`.".format(command, cwd))
        if click.confirm('Do you want to continue?'):
            subprocess.check_call(command, cwd=cwd)
            pr = repo.create_pull(title, "master", branch, body=body)
            click.secho("created pull request {}".format(pr.html_url))


def get_reponame(username, organization):
    return "{}-{}".format(organization.lower(), username.lower())

# def get_reponame(username, organization):
#     return "examen-{}".format(username.lower())


def generate_from_template(path, username, clone_url, repo_name):
    """generate_from_template fills in the provided jinja2 template. If the filename ends with
    `.jinja`, the template file is removed and the result is saved without that extension. If not,
    the template file is overwritten with the generated result.
    """
    template = jinja2.Template(open(path).read())
    outputText = template.render(
        username=username,
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
    required="True")
@click.option(
    '--students',
    help='comma-separated list of students',
    required="True")
@click.option(
    '--comments',
    help='optional comma-separated list of comments',
    required="False")
def create_repos(ctx, source, students, comments):
    """Create student repositories in the organization specified by the url.
    Each repository will contain a copy of the specified source and will have force-pushing disabled
    so students can not rewrite history.

    Note: this command does not grant students access to those repositories. See `assignment grant`.
    """
    organization = urlparse(ctx.obj['url']).path.rstrip("/").rsplit("/", 1)[-1]
    students = students.split(",")
    if comments:
        comments = comments.split(",")
        assert(len(students) == len(comments))

    click.secho("# Creating student repositories..", fg="green")
    click.secho("# Org: '{}'".format(organization), fg="green")
    click.secho("# Path: '{}'".format(source), fg="green")
    click.secho("# Students: '{}'".format(students), fg="green")

    g = ctx.obj['gh']
    pyg = ctx.obj['pyg']

    org = g.organization(organization)

    for idx, student in enumerate(students):
        click.secho("\n\nPreparing repo for {}".format(student), fg="green")

        reponame = get_reponame(student, organization)
        try:
            repo = org.create_repository(reponame, private=True)
        except Exception:
            repo = g.repository(organization, reponame)

        subprocess.check_call(["git", "checkout", "master"], cwd=source)
        subprocess.call(["git", "branch", "-D", student], cwd=source)
        subprocess.check_call(["git", "checkout", "-b", student], cwd=source)

        if os.path.isfile("{}/README.md.jinja".format(source)):
            generate_from_template(
                "{}/README.md.jinja".format(source),
                username=student,
                clone_url=repo.clone_url,
                repo_name=reponame)
        subprocess.check_call(["git", "add", "-A"], cwd=source)
        subprocess.call(["git", "commit", "-m", "fill in templates"], cwd=source)
        click.secho("Pushing source to {}".format(repo.ssh_url), fg="green")
        subprocess.check_call(["git", "push", repo.ssh_url, "{}:master".format(student)], cwd=source)
        subprocess.check_call(["git", "checkout", "master"], cwd=source)

        click.secho("Protecting the master branch so students can't rewrite history", fg="green")
        
        pygrepo = pyg.get_repo("{}/{}".format(organization, reponame))
        pygmaster = pygrepo.get_branch("master")
        pygmaster.edit_protection()

        if comments:
            click.secho("Adding comment to repo", fg="green")
            pygrepo.edit(description=comments[idx])


@assignment.command()
@click.pass_context
@click.option(
    '--source',
    help='path to repo with start code',
    required="True")
@click.option(
    '--students',
    help='comma-separated list of students',
    required="True")
def pull(ctx, source, students):
    """Show the latest commit of each student
    """
    organization = urlparse(ctx.obj['url']).path.rstrip("/").rsplit("/", 1)[-1]
    students = students.split(",")

    click.secho("# Showing the latest commit..", fg="green")
    click.secho("# Org: '{}'".format(organization), fg="green")
    click.secho("# Path: '{}'".format(source), fg="green")
    click.secho("# Students: '{}'".format(students), fg="green")

    g = ctx.obj['gh']
    summary = []

    try:
        for student in students:
            reponame = get_reponame(student, organization)
            repo = g.repository(organization, reponame)

            subprocess.check_call(["git", "checkout", student], cwd=source)

            subprocess.check_call(["git", "pull", repo.ssh_url, "master:{}".format(student)], cwd=source)

            timestamp = subprocess.check_output(["git", "log", "-1", "--pretty=format:%ct"], cwd=source, universal_newlines=True).rstrip()
            commit_summary = subprocess.check_output(["git", "log", "-1", "--pretty=format:%s"], cwd=source, universal_newlines=True)
            committer = subprocess.check_output(["git", "log", "-1", "--pretty=format:%an <%ae>"], cwd=source, universal_newlines=True)

            commit_time = datetime.fromtimestamp(int(timestamp))
            summary.append((student, repo.description, commit_time, committer, commit_summary))
    finally:
        subprocess.check_call(["git", "checkout", "master"], cwd=source)
        summary.sort(key=lambda tup: tup[2])
        click.secho(tabulate(summary, headers=['Username', "Description", 'Last commit time', "Committer info", 'Commit summary']))


@assignment.command()
@click.pass_context
@click.option(
    '--students',
    help='list of students',
    required="True")
def grant(ctx, students):
    """Grant each student push access (the collaborator role) to their repository in the
    organization specified by the url.
    """
    organization = urlparse(ctx.obj['url']).path.rstrip("/").rsplit("/", 1)[-1]
    students = students.split(",")

    click.secho("# Granting students write permission to their repository..", fg="green")
    click.secho("# Org: '{}'".format(organization), fg="green")
    click.secho("# Students: '{}'".format(students), fg="green")

    g = ctx.obj['gh']

    for student in students:
        reponame = get_reponame(student, organization)
        repo = g.repository(organization, reponame)

        click.secho("Adding the student as collaborator", fg="green")
        repo.add_collaborator(student)


@assignment.command()
@click.pass_context
@click.option(
    '--students',
    help='list of students',
    required="True")
def remove_grant(ctx, students):
    """Removes students' push access to their repository and cancels any open invitation for that
    student.
    """
    organization = urlparse(ctx.obj['url']).path.rstrip("/").rsplit("/", 1)[-1]
    students = students.split(",")

    click.secho("# Removing students write permission to their repository..", fg="green")
    click.secho("# Org: '{}'".format(organization), fg="green")
    click.secho("# Students: '{}'".format(students), fg="green")

    g = ctx.obj['gh']

    for student in students:
        reponame = get_reponame(student, organization)
        repo = g.repository(organization, reponame)

        # Delete open invitations for that user
        # Do this before removing as collaborator so we don't get a race condition where
        # student accepts invitation between the remove as collaborator and the remove
        # of the invitation.
        for invitation in repo.invitations():
            if str(invitation.invitee) == student:
                click.secho("Removing invitation for student '{}' for repo '{}'".format(
                    student, reponame), fg="green")
                invitation.delete()

        click.secho("Removing the student '{}' as collaborator from '{}'".format(
            student, reponame), fg="green")
        repo.remove_collaborator(student)
