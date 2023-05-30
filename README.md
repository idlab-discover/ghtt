# ghtt: Manage student projects and exams using GitHub

`ghtt` is a tool to help teachers run projects and exams on GitHub.

* Create individual or group repositories, issues and pull requests from templates.
* Grant and remove students access to individual or group repositories
* Download students solutions
* Integrate with Visual Studio Code to periodically submit solutions during exams.

It works both with GitHub.com and private GitHub Enterprise instances.

## Installation

> `ghtt` only runs on Linux and macOS, but Windows users can install [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) to run Ubuntu on Windows.

You can install `ghtt` by downloading the sources and installing it using `pip`.

```shell
git clone git@github.com:IBCNServices/ghtt.git
python3 -m pip install ./ghtt
```

After this, you can use it on your system!

## Usage

### Authentication

`ghtt` _requires two_ forms of authentication.

* SSH keys are used to push and pull from and to repositories. For more information on how to set this up, see [Adding a new SSH key to your GitHub account](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/adding-a-new-ssh-key-to-your-github-account).
* To create issues and manage repositories, `ghtt` requires a second form of authentication. The easiest option for authentication is a [GitHub Personal Access Token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token). You then need to supply this token **to each command** using the `--token <token>` flag.

  Alternatively, if you do not specify a token, `ghtt` will ask you for your username and password with each command.

### Project configuration

Each project and exam you manage with `ghtt` needs a "project configuration directory". This directory contains configuration files and templates to use for that project or exam.

This repository includes [a sample project config directory](docs/examples/project-config/).

> Note: this project-config folder includes a git submodule. Run `git submodule update --init --recursive` to download all submodules of this repository before you start.

* `ghtt.yaml` is the main config file for that project. It specifies which GitHub organization to use, the default configuration of the repositories and more.
* `students.csv` is a CSV file containing the students and (optionally) which groups they're in. The first row of this CSV is expected to contain the column headers. The next rows are the students.
* `template/` is a GitHub repository that is used as the template for the student repositories.
* `lab1-assignment.yaml` is an issue template you can use to generate issues.

Each time you execute the `ghtt` command, it will look for the `ghtt.yaml` file in the _current working directory_. So make sure you `cd` to the project config directory before executing `ghtt`.

## Common workflow

First, create a project folder based on the example included in this repo. Afterwards, create a new GitHub organization and modify `ghtt.yaml` to point to it. Now make sure you are in the project config folder. For ease of use, you can add the token as a Bash variable.

```shell
cd project-config
export TOKEN=AAAAAAAAAAAAAA
```

Then you can use the `create-repos` command to generate the repositories based on the provided CSV of students.

```shell
# Create repositories for each student or group
python3 -m ghtt assignment --token $TOKEN create-repos
```

Students don't yet have access to these repositories. After you have checked if everything is correct, you can give the students access to the repositories using the `grant` command.

```shell
# Give all students access to their personal or group repository
python3 -m ghtt assignment --token $TOKEN grant
```

You can automatically create issues based on an assignment. You can use this to give students multiple assignments throughout the semester, for example.

```shell
# Create an issue in each repository based on the template.
ghtt assignment --token $TOKEN create-issues lab1-assignment.yaml
```

When the exam or a project finishes, you can remove the student's access using the `remove-grant` command.

```shell
# Remove access of all students
python3 -m ghtt assignment --token $TOKEN remove-grant
```

If you want to grade the solutions, you can download them all using the `pull` command. This will download the student repositories as branches in the `template` repository.

```shell
# Download all repositories to your local machine
# These will show up as branches in the template repository
python3 -m ghtt assignment --token $TOKEN pull
```

When the `template` repository contains all the student branches, you can turn these branches into folders using the following command.

```shell
# Turn all branches of the template repository to separate folders
# so each repository is now in its own folder in template.expanded/
ghtt util branches-to-folders template/
```
