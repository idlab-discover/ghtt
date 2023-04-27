#!/usr/bin/env python3
import subprocess
from functools import wraps
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
    '--csv',
    help='Use this flag when you want to keep the header of a (csv) file.',
    is_flag=True)
def grep_in(path, strings, csv=False):
    """Prints each line which contains one of the strings in the provided comma-separated list.

    FILENAME: name of file to search

    STRINGS: Comma-separated list of strings to search for
    """
    strings = strings.split(",")

    with open(path, "r") as f:
        lines = f.readlines()

        if csv:
            click.secho(lines.pop(0).strip())

        for line in lines:
            for string in strings:
                if string in line:
                    click.secho(line.strip())
                    break


@util.command()
@click.argument("source", required="True")
def branches_to_folders(source):
    """Expands a git repository so each branch is in a different folder.

    SOURCE: path to git repository
    """

    source = source.rstrip("/")
    branches = subprocess.check_output(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/*"], cwd=source, universal_newlines=True)
    branches = branches.strip().split("\n")

    os.mkdir("{}.expanded".format(source))

    for branch in branches:
        subprocess.check_call(["git", "checkout", branch], cwd=source)
        shutil.copytree(source, "{}.expanded/{}".format(source, branch))

    subprocess.check_call(["git", "checkout", "master"], cwd=source)
