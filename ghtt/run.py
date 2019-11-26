#!/usr/bin/env python3
import subprocess
from functools import wraps

import click
import github3
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
    return gh


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
        ctx.obj['gh'] = authenticate(url, token)
        return f(*args, **kwargs)
    return wrapper


@click.group()
@click.pass_context
def cli(ctx):
    ctx.obj = {}


@cli.command()
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


@cli.command()
@click.pass_context
@click.option(
    '--organization', '-o',
    help='Github organization where student repos are located',
    required="True")
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
@needs_auth
def update_pr(ctx, organization, branch, title, body, source):
    """Pushes updated code to a new branch on students repositories
    and creates a pr.
    """
    click.secho("# Organization: '{}'".format(organization), fg="green")
    click.secho("# Branch: '{}'".format(branch), fg="green")
    click.secho("# title: '{}'".format(title), fg="green")
    click.secho("# message: '{}'".format(body), fg="green")
    click.secho("# source directory: '{}'".format(source), fg="green")
    click.secho("# Creating update pr..", fg="green")

    click.confirm('Please check if the above information is correct.\nDo you want to continue?', abort=True)

    g = ctx.obj['gh']

    org = g.organization(organization)

    for repo in org.repositories():
        command = ["git", "push", repo.ssh_url, "master:{}".format(branch)]
        cwd = source
        print("\nwill run `{}`\nin directory `{}`.".format(command, cwd))
        if click.confirm('Do you want to continue?'):
            subprocess.check_call(
                command, cwd=cwd
            )
            pr = repo.create_pull(title, "master", branch, body=body)
            click.secho("created pull request {}".format(pr.html_url))


# @cli.command()
# @click.pass_context
# def test(ctx):
#     """test function"""
#     click.secho("test")


if __name__ == "__main__":
    cli() #pylint: disable=E1123,E1120