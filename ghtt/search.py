#!/usr/bin/env python3
import subprocess
from functools import wraps

import click
import github3
import requests

from .auth import needs_auth


def notify(api_key, domain_name, to, results, query):
    url = 'https://api.mailgun.net/v3/{}/messages'.format(domain_name)
    auth = ('api', api_key)

    text = ""
    for result in results:
        text = text + result.html_url
        commit = next(result.commits())
        text = text + "\nMetadata of last commit:"
        text = text + "\n\tAuthor name: {}".format(commit.commit.author["name"])
        text = text + "\n\tAuthor email: {}".format(commit.commit.author["email"])
        text = text + "\n"

    data = {
        'from': 'ghtt <mailgun@{}>'.format(domain_name),
        'to': to,
        'subject': "Alert! Repositories found who match query '{}'\n".format(query),
        'text': text,
    }

    response = requests.post(url, auth=auth, data=data)
    response.raise_for_status()


def repos_matching(gh, query):
    repos = set()
    results = gh.search_code(query)
    for result in results:
        repos.add(result.repository)
    return repos


@click.command()
@click.pass_context
@click.option(
    '--query', '-q',
    help='Query to run. e.g. "Allkit.h in:path" ',
    required="True")
@click.option(
    '--mg-api-key',
    help='Mailgun api key.')
@click.option(
    '--mg-domain',
    help='Mailgun domain name.')
@click.option(
    '--to',
    help='Email address to send alert to.')
@needs_auth
def search(ctx, query, mg_api_key, mg_domain, to):
    """Searches repositories matching the query,
    prints the matching repositories, name and email address of the last committer,
    and optionally emails this info using Mailgun.

    for more info on possible query patterns see
    https://developer.github.com/v3/search/#search-code

    \b
    Examples:
      * `./ghtt search -t "<github-token>" -u github.ugent.be -q "Allkit.h in:path"`
      * `./ghtt search -t "<github-token>" -u github.ugent.be -q "Allkit.h in:path" --mg-api-key <mailgun-api-key> --mg-domain <mailgun-url> --to <email-address>`
    """
    click.secho("# Query: '{}'".format(query), fg="green")
    click.secho("# Searching for repositories..", fg="green")

    g = ctx.obj['gh']

    # https://developer.github.com/v3/search/#considerations-for-code-search
    results = repos_matching(g, query)
    if not results:
        click.secho("no results")
    for result in results:
        click.secho(result.html_url, fg="red")

        click.secho("Metadata of last commit:")
        commit = next(result.commits())
        click.secho("\tAuthor name: {}".format(commit.commit.author["name"]))
        click.secho("\tAuthor email: {}\n".format(commit.commit.author["email"]))


    if results and mg_api_key and mg_domain and to:
        click.secho("Sending email")
        notify(mg_api_key, mg_domain, to, results, query)