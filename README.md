# ghtt: Manage student projects and exams using GitHub

`ghtt` is a tool to help teachers run projects and exams on GitHub.

* Create individual or group repositories, issues and pull requests from templates.
* Grant and remove students access to individual or group repositories
* Download students solutions
* Integrate with Visual Studio Code to periodically submit solutions during exams.

It works both with GitHub.com and private GitHub Enterprise instances.

## Installation

> `ghtt` only runs on Linux, but Windows users can install [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) to run Ubuntu on Windows.

You can install `ghtt` by downloading the sources and installing it using `pip`.

```shell
git clone git@github.com:IBCNServices/ghtt.git
python3 -m pip install ./ghtt
```

After this, you can use it on your system!

## Usage

### Authentication

The easiest option for authentication is a [GitHub Personal Access Token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token). That way, you can quickly run commands without having to fill in your username and password.

```shell
ghtt assignment --token AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA grant
```

### Project configuration

Each project and exam you manage with `ghtt` needs a "project configuration directory". This directory contains configuration files and templates to use for that project or exam.

This repository includes [a sample project config directory](docs/examples/project-config/).

* `ghtt.yaml` is the main config file for that project. It specifies which GitHub organization to use, the default configuration of the repositories and more.
* `students.csv` is a CSV file containing the students and (optionally) which groups they're in. The first row of this CSV is expected to contain the column headers. The next rows are the students.
* `template/` is a GitHub repository that is used as the template for the student repositories.
* `lab1-assignment.yaml` is an issue template you can use to generate issues.

Each time you execute the `ghtt` command, it will look for the `ghtt.yaml` file in the _current working directory_. So make sure you `cd` to the project config directory before executing `ghtt`.
