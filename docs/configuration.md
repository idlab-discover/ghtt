# Configuring ghtt

`ghtt.yaml` is optional. Everything it holds can also be given on the command
line, so you can run `ghtt` without a config file at all. A config file is
simply the convenient way to stop retyping the same values for one course.

A complete example lives in
[`docs/examples/project-config/`](examples/project-config/).

## Where values come from

Each value is taken from the first source that supplies it:

1. the command line
2. the selected config file
3. the built-in default documented below

`ghtt` looks for `./ghtt.yaml` only when a command needs a value that was not
given on the command line. Pass `--config PATH` to select a different file; a
file named that way must exist, while a missing `./ghtt.yaml` is not an error.

Paths inside a config file are resolved relative to that file, not to the
directory you happen to run `ghtt` from.

`--help` never reads a config file, never prompts, and never contacts GitHub.

## Where options go

Options shared by all assignment commands are given **before** the subcommand:

```shell
ghtt assignment --token "$GHTT_TOKEN" --students-file students.csv create-repos
```

Options that belong to one command are given after it:

```shell
ghtt assignment create-pr --branch lab2 --title "Lab 2" --body "Here is lab 2."
```

## Settings

### Instance and authentication

| YAML key | CLI option | Default | Meaning |
| --- | --- | --- | --- |
| `url` | `--url`, `-u` | `https://github.com` | GitHub instance. The legacy form ending in the organization, such as `https://github.example.edu/algorithms-2026`, is still accepted and supplies the organization. |
| — | `--organization` | from `url` | Organization holding the student repositories. Overrides the organization in a legacy `url`. |
| — | `--token`, `-t` | — | Personal access token. Can also be given as the `GHTT_TOKEN` environment variable. Always required; see below. |
| `transport` | `--transport` | `https` | Git transport for pushing and fetching: `https` uses the token, `ssh` uses your own SSH key. |

Every assignment command needs a token, whichever transport you choose.
Creating repositories, setting descriptions, protecting branches, adding
collaborators, and opening issues and pull requests all go through the GitHub
API, and an SSH key cannot authenticate there. `--transport ssh` changes only
how Git pushes and fetches.

### Repositories

| YAML key | CLI option | Default | Meaning |
| --- | --- | --- | --- |
| `source` | `--source`, `-s` | — | Local Git repository holding the assignment source code. |
| `default-branch` | `--default-branch` | `master` | Branch created in new repositories and used as the base branch of pull requests. |
| `repos.name-template` | `--repo-name-template` | see below | Pattern for repository names. |
| `repos.has-issues` | `--has-issues` | `false` | Enable issues on new repositories. |
| `repos.has-wiki` | `--has-wiki` | `false` | Enable wikis on new repositories. |
| `repos.require-pull-requests` | `--require-pull-requests` | `false` | Require a pull request before merging into a protected branch. |
| `repos.protect-branches` | `--protect-branch` | none | Additional branches to protect, by exact name. Repeat the option for more than one. |
| `enable-repo-delete` | `--enable-repo-delete` | `false` | Second opt-in required by `delete-repos`. |

The name template understands three placeholders: `{organization}`,
`{student_username}`, and `{student_group}`. Any other placeholder is rejected
before anything is created. Without a template, ghtt uses
`{organization}-{student_group}` for group work and
`{organization}-{student_username}` for individual work.

The default branch of a new repository is always protected. `protect-branches`
adds more. See [Branch protection](#branch-protection) for the limits.

### Students and mentors

| YAML key | CLI option | Meaning |
| --- | --- | --- |
| `students.source` | `--students-file` | CSV file listing the students. |
| `students.field-mapping.username` | `--student-username-field` | Column holding GitHub usernames. A leading `#` is stripped. |
| `students.field-mapping.comment` | `--student-comment-template` | Jinja template for the student's part of the repository description. `record` holds the student's CSV row. |
| `students.field-mapping.group` | `--student-group-field` | Column holding one group name per student. |
| `students.field-mapping.groups` | `--student-groups-field` | Column holding a comma-separated list of groups. The student joins the repository of every group listed. |
| `mentors.source` | `--mentors-file` | CSV file listing the mentors. |
| `mentors.field-mapping.username` | `--mentor-username-field` | Mentor username column. |
| `mentors.field-mapping.comment` | `--mentor-comment-template` | Jinja template for a mentor description. |
| `mentors.field-mapping.groups` | `--mentor-groups-field` | Column holding the groups a mentor guides. |

Set either `group` or `groups`, never both: they describe the same thing in
incompatible ways, and ghtt refuses a file that sets both rather than guessing.

Group names are normalized before they are compared or used in a repository
name: they are lower-cased and every run of non-alphanumeric characters becomes
a single hyphen. `Project / Team 1` and `project-team-1` are the same group.

A mentor belongs to every repository whose group appears in their own group
list. Individual repositories have no group, so they have no mentors.

### Validation

| YAML key | CLI option | Default | Meaning |
| --- | --- | --- | --- |
| `expected-group-size` | `--expected-group-size` | `0` | Students expected per repository. |
| `expected-mentors-per-group` | `--expected-mentors-per-group` | `0` | Mentors expected per repository. |

A count of `0` disables its own check. When a repository does not match, ghtt
lists the people it found and asks whether to continue with that one
repository. `0` is the built-in default, but the example config sets a real
group size, which is what you want for group work.

## Selecting repositories

`--students` and `--groups` are **filters over the configured student list**,
not a way to supply students. Both take a comma-separated list, and a
repository is selected when it satisfies every filter you supply:

```shell
# Every repository
ghtt assignment grant

# Only ada's repository, and only if it is a Team 1 repository
ghtt assignment grant --students ada --groups "Team 1"
```

Selecting one member of a group selects their whole group repository; it does
not remove their teammates from it.

## The JSON Schema

`ghtt config schema` prints the JSON Schema of `ghtt.yaml` for the version you
have installed. Feed it to an editor for completion and validation:

```shell
ghtt config schema > ghtt-schema.json
```

The schema is tied to the ghtt version. There is no separate config version.

## Template files

Every file in the source repository whose name ends in `.jinja` is rendered for
each target repository, and the rendered file replaces it without that suffix:
`README.md.jinja` becomes `README.md`. Rendering happens in a temporary copy,
so your own source repository is never modified.

These variables are available:

| Variable | Meaning |
| --- | --- |
| `clone_url` | Clone URL of the repository being created, for the selected transport. |
| `organization` | Target organization. |
| `group` | Normalized group name, or nothing for individual repositories. |
| `students` | The students of this repository. Each has `username`, `comment`, `groups`, and `record`. |
| `mentors` | The mentors of this repository, with the same fields. |
| `repo` | The repository itself: `name`, `organization`, `group`, `description`, `url`, `students`, `mentors`. |

An undefined variable is an error rather than an empty string, so a typo in a
template is reported instead of quietly producing a broken file.

`record` holds a student's whole row from the student list, keyed by the CSV
column headers. That is how a value that differs per student, such as a personal
API key, reaches only that student's repository. See
[unique-content.md](unique-content.md) for that workflow.

## Content paths

`create-repos` and `create-pr` accept `--content-dir` and `--content-file`, the
files to write into each repository besides the source. Both options are
repeatable, and both accept the placeholders of a repository name --
`{organization}`, `{student_username}`, and `{student_group}` -- in their paths,
so each student or group can be handed a file that only they receive:

```shell
ghtt assignment create-pr \
  --content-dir handouts/lab3/common \
  --content-dir 'handouts/lab3/{student_group}' \
  --content-file 'kubeconfigs/{student_group}.yaml=.kube/config' \
  --branch kubeconfig --title "Your cluster access" --body "Merge this."
```

Directories are applied in the order given and mapped files after all of them,
so a later entry replaces a file an earlier one wrote. An unknown placeholder,
a `--content-file` without both halves, and a destination that would leave the
repository are all refused before anything is created. These options are
command-line only; they describe one hand-out rather than a course-wide default.
See [unique-content.md](unique-content.md#a-file-that-cannot-fit-in-the-student-list).

## Issue templates

`ghtt assignment create-issues PATH` takes a YAML file that is itself a Jinja
template, rendered separately for every repository with the variables above.
After rendering it must be a non-empty list of milestones and issues:

```yaml
- type: milestone
  title: Deadline lab 1
  due date: 2026-03-09
  description: Hand in lab 1 before the lecture.
- type: issue
  title: Assignment lab 1
  milestone: Deadline lab 1
  labels:
    - assignment
  assignees:
    - jdoe
  body: |
    Clone your repository from {{ clone_url }}.

    Good luck, {{ students[0].comment }}!
```

A milestone accepts `title`, `description`, and `due date` (also spelled
`due-date`). An issue accepts `title`, `body`, `milestone`, `labels`, and
`assignees`.

Entries are matched by title within their repository. An entry that already
exists is updated only when it differs, so running the command again after
editing the template is safe. A milestone referred to by an issue must be
defined in the same template or already exist in the repository; that is
checked before anything is created.

A due date without a time means midnight **in the timezone of the machine
running ghtt**. GitHub stores a due date as a day rather than an instant, so
ghtt compares only the day when deciding whether a milestone changed.

If an assignee cannot be assigned, because they have no GitHub account or no
access to the repository, the issue is created without assignees and the
problem is reported. The assignment text is worth more than its assignees.

## Branch protection

ghtt protects a branch by its exact name, which is what GitHub's branch
protection API accepts. Wildcard patterns such as `release/*` need GitHub
repository rulesets, which ghtt cannot configure, so they are **refused** with
an explanation rather than silently ignored.

A named branch that does not exist in the new repository cannot be protected
either. ghtt reports that as a failure of that repository, so a run never
reports success over an unprotected branch.
