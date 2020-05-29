#!/usr/bin/env python3
import subprocess
from functools import wraps
import os

import click
import github3
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
def grep_in(path, strings):
    """Prints each line which contains one of the strings in the provided comma-separated list.

    FILENAME: name of file to search

    STRINGS: Comma-separated list of strings to search for
    """
    strings = strings.split(",")

    with open(path, "r") as f:
        lines = f.readlines()

    for line in lines:
        for string in strings:
            if string in line:
                click.secho(line.strip())
                break
