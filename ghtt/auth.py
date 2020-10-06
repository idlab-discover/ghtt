#!/usr/bin/env python3
from functools import wraps
import subprocess
from urllib.parse import urlparse

import click
import github as pygithub
import requests

import ghtt.config

def authenticate(url, token):
    click.secho("# URL: '{}'".format(url), fg="green")

    if not token:
        username = click.prompt("{} Username".format(url))
        token = username
        password = click.prompt("{} Password".format(url), hide_input=True)
    else:
        username = ""
        password = ""

    if not url.startswith("http"):
        url = "https://" + url

    url = urlparse(url)

    if url.netloc == "github.com":
        pyg = pygithub.Github(
            login_or_token=token,
            password=password)
    else:
        pyg = pygithub.Github(
            base_url="https://{url.netloc}/api/v3".format(url=url),
            login_or_token=token,
            password=password)

    return pyg


def needs_auth(f):
    @wraps(f)
    @click.option(
        '--url', '-u',
        help='URL to Github instance. Defaults to github.com.',
        default=lambda: ghtt.config.get('url', "https://github.com"))
    @click.option(
        '--token', '-t',
        help='Github authentication token.')
    @click.pass_context
    def wrapper(ctx, *args, url=None, token=None, **kwargs):
        ctx.obj['pyg'] = authenticate(url, token)
        ctx.obj['url'] = url
        return f(*args, **kwargs)
    return wrapper