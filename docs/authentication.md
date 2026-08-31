# Authentication and token permissions

Every `ghtt` command that touches GitHub authenticates with a **personal access
token**. This page explains how to create one, which permissions it needs, and
which of those permissions each command actually uses.

Give the token with `--token`, or put it in `GHTT_TOKEN`:

```shell
export GHTT_TOKEN=github_pat_11AAAAAAA0aaaaaaaaaaaa
```

## Which kind of token

GitHub has two kinds, and `ghtt` works with both.

- A **fine-grained token** is the one to prefer. It is scoped to a single
  organization and to the permissions you tick, so a stolen token cannot reach
  your other courses or your own repositories.
- A **classic token** is the fallback for an older GitHub Enterprise Server that
  does not offer fine-grained tokens yet. It is scoped by coarse OAuth scopes and
  covers everything you personally have access to.

A token can never do more than you can. Creating repositories, protecting
branches, and adding collaborators are owner-level actions, so you need the
matching role in the organization no matter which token you use.

## Creating a fine-grained token

1. Go to **Settings → Developer settings → Personal access tokens →
   Fine-grained tokens** and choose **Generate new token**.
2. **Resource owner:** select the **organization** that holds the student
   repositories, not your own account. A token owned by your account cannot act
   on organization repositories.
3. **Expiration:** pick a date past the end of the course. `ghtt` fails with an
   authentication error the moment the token expires.
4. **Repository access:** choose **All repositories**. `ghtt assignment
   create-repos` creates repositories that do not exist yet, and a token limited
   to *selected* repositories cannot create new ones — you would have to edit the
   token after every run.
5. **Permissions:** tick the repository permissions in the table below.
6. Generate the token and copy it. GitHub shows it once.

Two organization settings can block the token before it is ever used:

- The organization must **allow access via fine-grained tokens**
  (*Organization settings → Personal access tokens*).
- If the organization requires approval, the token stays **pending** until an
  organization owner approves it, and until then it can only see public data.
  Requests by organization owners are approved automatically.

## Permissions for all of ghtt

These are the repository permissions that cover every `ghtt` command. It is the
list to use when you want one token for the whole course.

| Repository permission | Access |
| --- | --- |
| Administration | Read and write |
| Contents | Read and write |
| Issues | Read and write |
| Pull requests | Read and write |
| Metadata | Read (mandatory, ticked for you) |

No organization-level permission is needed: `ghtt` reads and writes
repositories, never organization settings, members, or teams.

## Permissions per command

Every command additionally needs **Metadata: read**, which GitHub grants to
every fine-grained token automatically. `ghtt` lists the organization's
repositories before it acts, and that listing is a Metadata read.

| Command | Permissions it uses | Why |
| --- | --- | --- |
| `assignment create-repos` | Administration: **write**, Contents: **write** | Creates the repository, sets its description and default branch, and installs the branch-protection rulesets (Administration). Pushes the rendered source over HTTPS (Contents). |
| `assignment create-pr` | Contents: **write**, Pull requests: **write** | Pushes the branch (Contents) and opens the pull request, reusing an open one if it exists (Pull requests). |
| `assignment create-issues` | Issues: **write** | Creates and updates both the milestones and the issues of the template. GitHub counts milestones under Issues, and lists them under Pull requests as well, so add Pull requests: read if a milestone is refused. |
| `assignment pull` | Contents: **read** | Fetches each student repository over HTTPS. |
| `assignment grant` | Administration: **write** | Adding a collaborator to a repository is an administration action. |
| `assignment remove-grant` | Administration: **write** | Lists and cancels pending invitations and removes collaborators. |
| `assignment delete-repos` | Administration: **write** | Deletes repositories. |
| `assignment rename-repo` | Administration: **write** | Renames repositories. |
| `search` | Contents: **read** | Searches code and reads the last commit of the default branch. See the note below. |
| `config schema`, `util grep-in`, `util branches-to-folders` | none | These never contact GitHub. |

Two things shift what a run needs:

- **`--transport ssh`** makes Git push and fetch with your own SSH key, so
  Contents is no longer used for that. The token is still required for
  everything `ghtt` does through the API, because the GitHub API cannot
  authenticate with an SSH key.
- **`--dry-run`** still lists the organization's repositories, so it needs
  Metadata: read and a valid token, but it performs none of the writes above.

### A note on `ghtt search`

`search` is the one command a fine-grained token may not be able to run. Code
search spans all of GitHub, while a fine-grained token is scoped to one resource
owner, and GitHub does not document `GET /search/code` as supported for
fine-grained tokens. If the command returns nothing or fails with a permission
error, use a classic token with the `repo` scope for that command alone.

## Permissions ghtt does not need

Tokens are easier to trust when it is clear what is *not* on them. `ghtt` never
calls the endpoints behind these permissions, so leave them at *No access*:

- **Commit statuses**, **Checks**, **Actions**, **Workflows** — `ghtt` neither
  reads nor writes CI state.
- **Custom properties** — repositories are created without them.
- **Webhooks**, **Environments**, **Secrets**, **Variables**, **Pages**.
- Every **organization** and **account** permission, including Members.

## Classic tokens

On an instance without fine-grained tokens, create a classic token with:

- **`repo`** — covers repository contents, issues, pull requests, collaborators,
  and rulesets for every repository you can reach.
- **`delete_repo`** — only if you intend to use `assignment delete-repos`.

`repo` is a broad scope: it applies to every repository your account can access,
including private ones outside the course. Set a short expiration and keep the
token to the machine you teach from.

## When a command reports a permission problem

`ghtt` turns the API's status codes into a sentence naming the action and the
repository. The three you are most likely to see:

- **`authentication failed; check --token`** (401) — the token is mistyped,
  revoked, or expired.
- **`permission denied; check the token scopes and organization role`** (403) —
  the token is valid but lacks the permission in the table above, or your own
  role in the organization does not allow the action. A fine-grained token
  awaiting organization approval also lands here.
- **`it was not found or the token cannot access it`** (404) — GitHub hides
  what a token may not see, so this is a missing repository *or* a missing
  permission. On `create-repos`, it usually means the token is limited to
  selected repositories instead of all of them.

A few failures are not about permissions at all. `grant` skips a student with a
warning when their username does not exist, and organizations that forbid
inviting outside collaborators reject students who are not organization members
regardless of the token.
