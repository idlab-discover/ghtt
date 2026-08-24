"""Built-in defaults and the external names ghtt exchanges with other systems.

Every literal that a user can see, configure, or depend on lives here so that a
default can be reviewed in one place instead of being rediscovered in each
command. Values are grouped by the system they belong to.
"""

from __future__ import annotations

from enum import StrEnum

# ==============================================================================
# ghtt Project Files
# ==============================================================================

#: Name searched in the current directory when no ``--config`` is supplied.
CONFIG_FILENAME = "ghtt.yaml"

#: Suffix marking a file in the source repository as a Jinja template. The
#: rendered file keeps the same name without this suffix.
TEMPLATE_SUFFIX = ".jinja"

#: Directory suffix used by ``util branches-to-folders`` for its output.
EXPANDED_DIRECTORY_SUFFIX = ".expanded"

#: Separates the source from the destination of one ``--content-file`` mapping.
#: The last one in the value splits it, so a generated source name may itself
#: contain the separator.
CONTENT_FILE_SEPARATOR = "="


# ==============================================================================
# GitHub
# ==============================================================================

#: Used when neither the command line nor the config file names an instance.
DEFAULT_GITHUB_URL = "https://github.com"

#: GitHub Enterprise serves the v3 REST API below this path.
ENTERPRISE_API_PATH = "/api/v3"

#: Host that PyGithub already targets with its own built-in default.
GITHUB_COM_HOSTNAME = "github.com"


class CollaboratorPermission(StrEnum):
    """The GitHub collaborator roles that ``grant`` can assign."""

    PUSH = "push"
    PULL = "pull"


class RepositoryVisibility(StrEnum):
    """Repository visibilities ghtt is willing to create."""

    PRIVATE = "private"


# ==============================================================================
# Repository Naming
# ==============================================================================

#: Repository name used when every student gets their own repository.
INDIVIDUAL_NAME_TEMPLATE = "{organization}-{student_username}"

#: Repository name used when students are grouped into shared repositories.
GROUP_NAME_TEMPLATE = "{organization}-{student_group}"

#: The complete set of placeholders a name template may use.
NAME_TEMPLATE_PLACEHOLDERS = ("organization", "student_username", "student_group")


# ==============================================================================
# Git
# ==============================================================================

#: Branch created by ``create-pr`` when the caller does not name one.
DEFAULT_PULL_REQUEST_BRANCH = "ghtt-update"

#: Username part of the HTTPS URL that carries a token to a Git subprocess.
HTTPS_TOKEN_USERNAME = "x-access-token"


# ==============================================================================
# Mailgun
# ==============================================================================

#: Endpoint template used by ``search`` to send its optional notification.
MAILGUN_MESSAGE_URL = "https://api.mailgun.net/v3/{domain}/messages"
