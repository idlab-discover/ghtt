# ghtt: Manage student projects and exams using GitHub

`ghtt` is a tool to help teachers run projects and exams on GitHub.

- Create individual or group repositories, issues and pull requests from templates.
- Grant and remove students access to individual or group repositories.
- Download student solutions.
- Integrate with Visual Studio Code to periodically submit solutions during exams.

It works both with GitHub.com and private GitHub Enterprise instances.

## Installation

> `ghtt` only runs on Linux and macOS, but Windows users can install [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) to run Ubuntu on Windows.

You can install `ghtt` by downloading the sources and installing it using `uv`.

```shell
git clone git@github.com:idlab-discover/ghtt.git
uv tool install ./ghtt
```

After this, you can use it on your system!

## Usage

### Authentication

**A token is always required.** `ghtt` creates repositories, sets descriptions,
protects branches, adds collaborators, and opens issues and pull requests
through the GitHub API, which authenticates with a
[personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token).
Give it with `--token`, or put it in the `GHTT_TOKEN` environment variable so
you do not have to repeat it:

```shell
export GHTT_TOKEN=github_pat_11AAAAAAA0aaaaaaaaaaaa
```

By default the same token also pushes and fetches over HTTPS, so the token is
the only thing you have to set up. It is handed to Git one command at a time; it
is never written into a Git remote, a config file, or an error message.

`--transport ssh` makes Git push and fetch with the SSH keys you already have,
which is useful if your instance or your workflow expects SSH. It changes only
that: the token is still needed for everything ghtt does through the API. See
[Adding a new SSH key to your GitHub account](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/adding-a-new-ssh-key-to-your-github-account).

### Project configuration

Each project and exam you manage with `ghtt` needs a "project configuration
directory". This directory contains configuration files and templates to use
for that project or exam.

This repository includes [a sample project config directory](docs/examples/project-config/).

> Note: this project-config folder includes a git submodule. Run `git submodule update --init --recursive` to download all submodules of this repository before you start.

- `ghtt.yaml` is the main config file for that project. It specifies which GitHub organization to use, the default configuration of the repositories and more.
- `students.csv` is a CSV file containing the students and (optionally) which groups they're in. The first row of this CSV is expected to contain the column headers. The next rows are the students.
- `template/` is a GitHub repository that is used as the template for the student repositories.
- `lab1-assignment.yaml` is an issue template you can use to generate issues.

`ghtt` looks for `ghtt.yaml` in the _current working directory_, so `cd` to the
project config directory before running it. You can also point at a specific
file with `--config`, or skip the file entirely and pass every value on the
command line.

See [docs/configuration.md](docs/configuration.md) for every available setting,
the template variables, and the issue template format, and
[docs/unique-content.md](docs/unique-content.md) for giving each student their
own credentials, dataset, or exam variant.

## Common workflow

First, create a project folder based on the example included in this repo.
Afterwards, create a new GitHub organization and modify `ghtt.yaml` to point to
it. Now make sure you are in the project config folder.

```shell
cd project-config
export GHTT_TOKEN=github_pat_11AAAAAAA0aaaaaaaaaaaa
```

Then you can use the `create-repos` command to generate the repositories based
on the provided CSV of students.

```shell
# Create repositories for each student or group
ghtt assignment create-repos
```

Students don't yet have access to these repositories. After you have checked if
everything is correct, you can give the students access using the `grant`
command.

```shell
# Give all students access to their personal or group repository
ghtt assignment grant
```

You can automatically create issues based on an assignment. You can use this to
give students multiple assignments throughout the semester, for example.

```shell
# Create an issue in each repository based on the template
ghtt assignment create-issues lab1-assignment.yaml
```

When the exam or a project finishes, you can remove the students' access using
the `remove-grant` command.

```shell
# Remove access of all students
ghtt assignment remove-grant
```

If you want to grade the solutions, you can download them all using the `pull`
command. This downloads each student repository as a branch in your template
repository, without checking anything out.

```shell
# Download all repositories to your local machine
ghtt assignment pull
```

When the `template` repository contains all the student branches, you can turn
these branches into folders:

```shell
# Turn all branches of the template repository into separate folders
# so each repository is now in its own folder in template.expanded/
ghtt util branches-to-folders template/
```

## Commands

Run `ghtt <command> --help` for the full options of any command. Help works
offline: it never reads a config file, prompts, or contacts GitHub.

### `ghtt assignment`

| Command | Purpose |
| --- | --- |
| `create-repos` | Create a private repository per student or group from the source repository. `--content-dir` and `--content-file` add files that differ per student or group. |
| `create-pr` | Push a branch to the student repositories and open a pull request in each. `--content-dir` and `--content-file` hand out just those files, resolved and rendered per student or group; see [unique content](docs/unique-content.md). |
| `create-issues PATH` | Create or update the milestones and issues described by a template. |
| `pull` | Fetch each student repository into a local branch and show its last commit. |
| `grant` | Give students push access, or pull access with `--read-only`. |
| `remove-grant` | Remove student access and cancel pending invitations. |
| `delete-repos` | Permanently delete repositories. Needs two opt-ins; see below. |
| `rename-repo` | Rename organization repositories matching a regular expression. |

### `ghtt search`

Search GitHub code and print the last committer of each matching repository.
Optionally send the result by email through Mailgun.

### `ghtt util`

| Command | Purpose |
| --- | --- |
| `grep-in PATH STRINGS` | Print the lines of a file containing one of the comma-separated strings. |
| `branches-to-folders SOURCE` | Clone every local branch into its own folder in `SOURCE.expanded`. |

### `ghtt config`

`ghtt config schema` prints the JSON Schema of `ghtt.yaml` for the installed
version, so an editor can complete and validate the file.

## Working safely

Every command that changes something asks before it changes it, and answers
apply to one repository at a time. At each prompt you can answer `y`, `all`,
`n`, `none`, or `abort`. `--yes` selects everything without asking.

`--dry-run` shows the plan and every intended change without performing any of
them. Use it to check a run before it happens:

```shell
ghtt assignment --dry-run create-repos
```

Some safeguards are deliberately not skippable:

- `delete-repos` needs `--destroy-data` **and** `--enable-repo-delete` (or
  `enable-repo-delete: true` in `ghtt.yaml`). It confirms every repository
  separately, offers no answer that covers the rest, and does not accept
  `--yes`. Consider `rename-repo` instead; renaming keeps the data.
- `create-repos` never overwrites an existing repository. It skips it and says so.
- `branches-to-folders` refuses to write into an existing destination and never
  deletes files for you.

A command that could not finish for one repository keeps going with the others,
reports what failed at the end, and exits with a nonzero status.

## Development

```shell
uv sync                      # install the project and its dev dependencies
uv run pytest                # run the offline test suite
uv run ruff format .         # format
uv run ruff check .          # lint
uv run pyright               # type check
```

The whole suite runs offline: no test contacts GitHub. Tests against a real
disposable organization are marked `live` and are excluded by default; run them
with `uv run pytest -m live`.
