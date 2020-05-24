#!/usr/bin/env python3
import subprocess
from functools import wraps

import click
import github3
import github as pygithub
import requests

def authenticate(url, token):
    click.secho("# URL: '{}'".format(url), fg="green")

    if not token:
        username = click.prompt("{} Username".format(url))
        password = click.prompt("{} Password".format(url), hide_input=True)
    else:
        username = ""
        password = ""

    if not url.startswith("http"):
        url = "https://" + url
    if "github.com" in url:
        gh = github3.github.GitHub(
            token=token,
            username=username,
            password=password)
    else:
        gh = github3.github.GitHubEnterprise(
            url,
            token=token,
            username=username,
            password=password)


        # Protect using the pygithub library because it's not supported with github3.py
        pyg = pygithub.Github(
            base_url="{}/api/v3".format(url),
            login_or_token=token)

    return (gh, pyg)





def needs_auth(f):
    @wraps(f)
    @click.option(
        '--url', '-u',
        help='URL to Github instance. Defaults to github.com.',
        default="https://github.com")
    @click.option(
        '--token', '-t',
        help='Github authentication token.')
    @click.pass_context
    def wrapper(ctx, *args, url=None, token=None, **kwargs):
        (ctx.obj['gh'], ctx.obj['pyg']) = authenticate(url, token)
        return f(*args, **kwargs)
    return wrapper