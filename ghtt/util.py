#!/usr/bin/env python3
import subprocess
from functools import wraps
import sys
import os
import shutil

import click
import requests
import jinja2
import github as pygithub

from .auth import needs_auth

@click.group()
def util():
    pass

@util.command()
@click.argument("path", required="True")
@click.argument("strings", required="True")
@click.option(
    '--no-header',
    help='Use this flag when you want to remove the header of a file.',
    is_flag=True)
def grep_in(path, strings, no_header=False):
    """Prints each line which contains one of the strings in the provided comma-separated list.

    FILENAME: name of file to search

    STRINGS: Comma-separated list of strings to search for
    """
    strings = strings.split(",")

    with open(path, "r") as f:
        lines = f.readlines()

        if not no_header:
            click.secho(lines.pop(0).strip())

        for line in lines:
            for string in strings:
                if string in line:
                    click.secho(line.strip())
                    break


@util.command()
@click.argument("source", required="True")
@click.option(
    '--at', '-a',
    help='Time at which to show repository')
@click.option(
    '--rm-repo', '-r',
    help="Use this flag when you only want the files without the repository",
    is_flag=True)
def branches_to_folders(source, at=None, rm_repo=False):
    """Expands a git repository so each branch is in a different folder.

    SOURCE: path to git repository
    """
    source = os.path.abspath(source)
    source = source.rstrip("/")
    branches = subprocess.check_output(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/*"], cwd=source, universal_newlines=True)
    branches = branches.strip().split("\n")

    if os.path.exists(f"{source}.expanded"):
        click.secho(f"ERROR: the path '{source}.expanded' already exists. Please remove that directory first.", fg="red")
        return(False)
    os.mkdir(f"{source}.expanded")

    for branch in branches:
        destination = f"{source}.expanded/{branch}"
        subprocess.check_call(["git", "clone", "--single-branch", "--branch", branch, source, destination])
        if at:
            commit = subprocess.check_output(["git", "rev-list", "-n", "1", "--first-parent", f"--before='{at}'", branch], cwd=destination)
            commit = commit.decode(sys.stdout.encoding).rstrip()
            subprocess.check_call(["git", "-c", "advice.detachedHead=false", "checkout", commit], cwd=destination)
        if rm_repo:
            shutil.rmtree(f"{destination}/.git")

    subprocess.check_call(["git", "checkout", "master"], cwd=source)
