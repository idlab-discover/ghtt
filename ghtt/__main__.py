#!/usr/bin/env python3
import subprocess
from functools import wraps

import click
import github3
import requests

from .search import search
from .assignment import assignment
from .util import util


@click.group()
@click.pass_context
def cli(ctx):
    ctx.obj = {}


cli.add_command(search)
cli.add_command(assignment)
cli.add_command(util)


if __name__ == "__main__":
    cli() #pylint: disable=E1123,E1120
