# Upgrading from the previous ghtt

This release is a rewrite. Your existing `ghtt.yaml`, `students.csv`, issue
templates, and command lines keep working. This page lists what changed anyway,
either because the old behaviour was a bug or because it was unsafe.

## Nothing to change

- Every command and subcommand kept its name.
- Every option kept its name and short alias, including `--url`/`-u`,
  `--token`/`-t`, `--source`/`-s`, `--branch-already-pushed`/`-B`, `--yes`,
  `--students`, `--groups`, `--read-only`, `--destroy-data`, `--match`,
  `--replace`, `--at`/`-a`, `--rm-repo`/`-r`, and `--no-header`.
- Every `ghtt.yaml` key is still read, including the legacy `url` form that
  ends in the organization.
- The confirmation answers are still `y`, `all`, `n`, `none`, and `abort`.
- `{organization}`, `{student_username}`, and `{student_group}` still name
  repositories, and `.jinja` files are still rendered per repository.

## Fixed behaviour

**`create-repos` no longer modifies your source repository.** It used to check
out a branch named after each student repository *inside your own source*,
render the templates over your working tree, commit, and push. Every run left
one branch and one "fill in templates" commit per student behind, and a failure
partway through left rendered files where your templates used to be. Rendering
now happens in a temporary clone, and your source is untouched.

**`pull` no longer checks out a branch in your source.** It used to run
`git checkout <default-branch>` first, which moved your working tree. It now
fetches straight into a local branch per repository. A local branch that has
diverged is no longer silently overwritten either; pass `--force` if that is
what you want.

**`remove-grant` can now actually cancel an invitation.** The old code called
`Invitation.delete()` and `Invitation.invite_id`, neither of which exists in
PyGithub, so cancelling a pending invitation always raised `AttributeError`.

**`branches-to-folders --at` now matches commits.** The moment was passed to
Git as `--before='2026-01-31'` with the quotes included in the value, so it
never selected the commit you asked for.

**`create-issues` no longer rewrites unchanged milestones.** Due dates were
compared as exact instants against the time of day GitHub hands back, so every
run reported an update. Only the day is compared now.

**Multi-group students reach every group repository.** A student listed in
`groups` as `Team 1, Team 2` is now added to both repositories.

**`--help` works everywhere without a config file.** The old tool read
`ghtt.yaml` while building its options and exited if the file was missing, so
`ghtt --help` failed outside a project directory.

## Changed behaviour

**HTTPS is the default Git transport.** Pushing and fetching used SSH URLs
before. They now use HTTPS with your `--token`, so a token is the only thing
you need to set up. Add `--transport ssh`, or `transport: ssh` in `ghtt.yaml`,
to keep using your SSH keys for pushing and fetching. A token is still required
either way: the GitHub API cannot authenticate with an SSH key.

**Individual repositories no longer receive every mentor.** A mentor belongs to
the repositories of the groups in their own group list. Individual repositories
have no group, so they have no mentors. This matches what the old tool
effectively did.

**`create-issues` matches issues in any state.** It looked at open issues only,
so an issue you had closed was created a second time. It now matches closed
issues too and leaves them alone when they are up to date.

**A failed repository makes the command exit nonzero.** Failures used to be
printed as warnings and the command still reported success. Every command now
ends with a summary of what was processed, skipped, and failed, and exits
nonzero if anything failed.

**Bad input is reported instead of guessed.** A missing CSV column, a malformed
row, an unknown name-template placeholder, a duplicate repository name, a
config file setting both `group` and `groups`, or an unknown config key is now
an error naming the file and the field. The old tool would carry on with an
empty student list or an unexpected group.

**Templates fail on an undefined variable.** A typo in a `.jinja` file used to
render as an empty string. It is now an error that names the template.

## New

- `--dry-run` on every assignment command, and on `branches-to-folders`.
- `--organization` to name the organization separately from `--url`.
- A typed CLI option for every `ghtt.yaml` setting, so a config file is
  optional. See [configuration.md](configuration.md).
- `GHTT_TOKEN` as an alternative to `--token`.
- `--config PATH` to select a config file explicitly.
- `ghtt config schema` to print the JSON Schema of `ghtt.yaml`.
- `--protect-branch` and `repos.protect-branches` for branches to protect
  besides the default branch.
- `create-pr --content-dir DIR`, which writes just that directory's files into
  each repository, rendered for that student or group, on a branch cut from the
  repository's own default branch. Use it for per-student credentials or to
  correct one file across a class without disturbing anything else. It needs no
  access to the assignment template. See [unique-content.md](unique-content.md).
- `--content-dir` and `--content-file` on both `create-repos` and `create-pr`.
  Both are repeatable and both accept `{organization}`, `{student_username}`,
  and `{student_group}` in their paths, so a file generated per student or group
  -- a KUBECONFIG, a certificate, a dataset -- reaches only the repository it
  belongs to. `--content-file 'SOURCE=DESTINATION'` also renames it into place.
  See [unique-content.md](unique-content.md#a-file-that-cannot-fit-in-the-student-list).
- `create-pr --force-push` and `pull --force` for the cases that used to fail
  with a raw Git error.
- `grep-in` and the other local utilities report missing, empty, and unreadable
  files clearly.

## Known limits

Branch protection applies to branches named exactly. Wildcard patterns such as
`release/*` require GitHub repository rulesets, which ghtt cannot configure, so
they are refused with an explanation instead of being silently ignored.
