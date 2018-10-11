# gh-exam: helper script for running an exam on the UGent Github

## Creating student repositories

```bash
./gh-exam create -o <organization-name> -t <github-token> -s <path/to/assignment/repository>
```

This command creates a private repository for each student named `examen-<student-username>`.

* Each repository is located in the organization specified by `-o <organization-name>`
* Each repository contains the code in the git repository at `<path/to/assignment/repository>`
* Each repository is protected against force pushes. (rewrites of the git history)
* This command **does not** grant the students access to the repository, use the `grant` command for that.

## Granting students push-access to their repositories

```bash
./gh-exam grant -o <organization-name> -t <github-token>
```

This command grants each student push access to their repository in the specified organization.

## Removing students push-access to their repositories

```bash
./gh-exam remove-grant -o <organization-name> -t <github-token>
```

This command removes students' push access to their repository and cancels any open invitation for that student.
