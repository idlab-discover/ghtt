"""Templates render against a documented contract and fail loudly on a typo."""

from __future__ import annotations

from pathlib import Path

import pytest

from ghtt.templates import (
    ContentFile,
    ContentPlan,
    RenderError,
    build_content_plan,
    parse_content_file,
    render_content_path,
    render_text,
    render_tree,
    validate_content_plan,
    write_content,
)

from .factories import make_target

TARGET = make_target("course-team-1", students=("ada", "bert"), group="team-1")
CLONE_URL = "https://github.example.edu/course/course-team-1.git"


def test_every_documented_variable_is_available() -> None:
    template = (
        "{{ repo.name }}|{{ organization }}|{{ group }}|{{ clone_url }}|"
        "{{ students | length }}|{{ students[0].username }}|{{ repo.description }}"
    )

    assert render_text(template, TARGET, CLONE_URL) == (
        f"course-team-1|course|team-1|{CLONE_URL}|2|ada|Ada, Bert"
    )


def test_the_legacy_repo_comment_name_still_works() -> None:
    assert render_text("{{ repo.comment }}", TARGET, CLONE_URL) == "Ada, Bert"


def test_an_undefined_variable_is_reported_instead_of_rendered_empty() -> None:
    with pytest.raises(RenderError, match="course-team-1"):
        render_text("Hello {{ typo }}", TARGET, CLONE_URL)


def test_rendering_a_tree_replaces_each_template_with_its_output(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md.jinja").write_text("Clone {{ clone_url }}\n", "utf-8")
    (tmp_path / "docs" / "task.md.jinja").write_text("For {{ group }}\n", "utf-8")
    (tmp_path / "keep.txt").write_text("{{ not a template }}\n", "utf-8")

    rendered = render_tree(tmp_path, TARGET, CLONE_URL)

    assert sorted(path.name for path in rendered) == ["README.md", "task.md"]
    assert (tmp_path / "README.md").read_text("utf-8") == f"Clone {CLONE_URL}\n"
    assert (tmp_path / "docs" / "task.md").read_text("utf-8") == "For team-1\n"
    assert not (tmp_path / "README.md.jinja").exists()
    # A file that is not a template is left exactly as it was.
    assert (tmp_path / "keep.txt").read_text("utf-8") == "{{ not a template }}\n"


def test_git_data_is_never_treated_as_course_content(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hook.sample.jinja").write_text("{{ typo }}\n", "utf-8")

    assert render_tree(tmp_path, TARGET, CLONE_URL) == ()
    assert (tmp_path / ".git" / "hook.sample.jinja").exists()


# ==============================================================================
# Content plans
# ==============================================================================

INDIVIDUAL = make_target("course-ada", students=("ada",))


def plan(*directories: Path | str) -> ContentPlan:
    return ContentPlan(directories=tuple(str(directory) for directory in directories))


def test_a_content_file_is_mapped_from_its_source_to_its_destination() -> None:
    mapping = parse_content_file("kubeconfigs/{student_group}.yaml=.kube/config")

    assert mapping.source == "kubeconfigs/{student_group}.yaml"
    assert mapping.destination == ".kube/config"


def test_the_last_separator_splits_a_content_file() -> None:
    """A generated source name may itself contain the separator."""
    mapping = parse_content_file("out/key=value/{student_username}.pem=secrets/key.pem")

    assert mapping.source == "out/key=value/{student_username}.pem"
    assert mapping.destination == "secrets/key.pem"


@pytest.mark.parametrize(
    "value",
    ["kubeconfig.yaml", "=.kube/config", "kubeconfig.yaml="],
)
def test_a_content_file_without_both_halves_is_rejected(value: str) -> None:
    with pytest.raises(RenderError, match="SOURCE=DESTINATION"):
        parse_content_file(value)


@pytest.mark.parametrize("destination", ["/etc/passwd", "../elsewhere/config"])
def test_a_destination_may_not_leave_the_repository(destination: str) -> None:
    with pytest.raises(RenderError, match="inside the repository"):
        parse_content_file(f"source.yaml={destination}")


def test_an_unknown_placeholder_is_rejected_before_anything_runs() -> None:
    with pytest.raises(RenderError, match="student_name"):
        build_content_plan(["handouts/{student_name}"], None)

    with pytest.raises(RenderError, match="student_id"):
        build_content_plan(None, ["keys/{student_id}.pem=key.pem"])


def test_a_path_is_resolved_for_the_repository_it_belongs_to() -> None:
    assert render_content_path("handouts/{student_group}", TARGET) == Path(
        "handouts/team-1"
    )
    assert render_content_path("keys/{student_username}.pem", INDIVIDUAL) == Path(
        "keys/ada.pem"
    )
    assert render_content_path("{organization}/shared", TARGET) == Path("course/shared")


def test_a_username_cannot_stand_for_a_whole_group() -> None:
    """Nothing would tell you whose file the group received."""
    with pytest.raises(RenderError, match="group repository"):
        render_content_path("keys/{student_username}.pem", TARGET)


def test_an_individual_repository_has_no_group_to_name() -> None:
    with pytest.raises(RenderError, match="individual repository"):
        render_content_path("handouts/{student_group}", INDIVIDUAL)


def test_a_username_that_is_a_path_never_escapes_the_hand_out() -> None:
    escaping = make_target("course-evil", students=("../../.ssh",))

    with pytest.raises(RenderError, match="path separator"):
        render_content_path("handouts/{student_username}", escaping)


def test_a_shared_path_is_checked_once_instead_of_once_per_student(
    tmp_path: Path,
) -> None:
    """A path that is the same for everyone is a mistake about the whole run."""
    with pytest.raises(RenderError, match="Content directory not found"):
        validate_content_plan(plan(tmp_path / "absent"))

    (tmp_path / "empty").mkdir()
    with pytest.raises(RenderError, match="holds no files"):
        validate_content_plan(plan(tmp_path / "empty"))

    # A path with a placeholder differs per repository, so it can only be
    # checked once its repository is known.
    validate_content_plan(plan(tmp_path / "handouts" / "{student_group}"))


def test_content_is_written_where_the_repository_wants_it(tmp_path: Path) -> None:
    handout = tmp_path / "handout"
    (handout / "docs").mkdir(parents=True)
    (handout / "docs" / "task.md").write_text("Read this.\n", "utf-8")
    (handout / "credentials.env.jinja").write_text("GROUP={{ group }}\n", "utf-8")
    (tmp_path / "kubeconfigs").mkdir()
    (tmp_path / "kubeconfigs" / "team-1.yaml").write_text("clusters: []\n", "utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    changes = write_content(
        ContentPlan(
            directories=(str(handout),),
            files=(
                ContentFile(
                    source=str(tmp_path / "kubeconfigs" / "{student_group}.yaml"),
                    destination=".kube/config",
                ),
            ),
        ),
        workspace,
        TARGET,
        CLONE_URL,
    )

    assert [change.path for change in changes] == [
        "credentials.env",
        "docs/task.md",
        ".kube/config",
    ]
    # A .jinja file is rendered for this repository and loses its suffix.
    assert (workspace / "credentials.env").read_text("utf-8") == "GROUP=team-1\n"
    assert (workspace / "docs" / "task.md").read_text("utf-8") == "Read this.\n"
    # A mapped file lands at the path it was given, whatever it was called.
    assert (workspace / ".kube" / "config").read_text("utf-8") == "clusters: []\n"


def test_a_later_directory_replaces_a_file_an_earlier_one_wrote(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "common"
    shared.mkdir()
    (shared / "config.yaml").write_text("shared\n", "utf-8")
    (shared / "README.md").write_text("Read me.\n", "utf-8")
    own = tmp_path / "team-1"
    own.mkdir()
    (own / "config.yaml").write_text("for team 1\n", "utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    changes = write_content(
        plan(shared, tmp_path / "{student_group}"), workspace, TARGET, CLONE_URL
    )

    assert (workspace / "config.yaml").read_text("utf-8") == "for team 1\n"
    assert (workspace / "README.md").read_text("utf-8") == "Read me.\n"
    # The replacement is reported rather than folded away silently.
    assert [change.describe() for change in changes] == [
        "+ README.md",
        "+ config.yaml",
        "~ config.yaml",
    ]


def test_a_generated_file_survives_byte_for_byte(tmp_path: Path) -> None:
    """A keystore or an archive must not be treated as text."""
    keys = tmp_path / "keys"
    keys.mkdir()
    payload = bytes(range(256))
    (keys / "team-1.p12").write_bytes(payload)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    write_content(
        ContentPlan(
            files=(
                ContentFile(
                    source=str(keys / "{student_group}.p12"),
                    destination="secrets/keystore.p12",
                ),
            )
        ),
        workspace,
        TARGET,
        CLONE_URL,
    )

    assert (workspace / "secrets" / "keystore.p12").read_bytes() == payload


def test_content_a_repository_does_not_have_is_reported_not_skipped(
    tmp_path: Path,
) -> None:
    """An empty hand-out is never delivered in place of a missing one."""
    with pytest.raises(RenderError, match="Content directory not found"):
        write_content(plan(tmp_path / "{student_group}"), tmp_path, TARGET, CLONE_URL)

    with pytest.raises(RenderError, match="Content file not found"):
        write_content(
            ContentPlan(
                files=(
                    ContentFile(
                        source=str(tmp_path / "{student_group}.yaml"),
                        destination=".kube/config",
                    ),
                )
            ),
            tmp_path,
            TARGET,
            CLONE_URL,
        )


def test_a_shared_file_that_does_not_exist_is_reported_before_the_run(
    tmp_path: Path,
) -> None:
    missing = ContentPlan(
        files=(
            ContentFile(
                source=str(tmp_path / "kubeconfig.yaml"), destination=".kube/config"
            ),
        )
    )

    with pytest.raises(RenderError, match="Content file not found"):
        validate_content_plan(missing)


def test_git_data_inside_a_content_directory_is_never_handed_out(
    tmp_path: Path,
) -> None:
    handout = tmp_path / "team-1"
    (handout / ".git").mkdir(parents=True)
    (handout / ".git" / "config").write_text("[core]\n", "utf-8")
    (handout / "config").write_text("cluster: team-1\n", "utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    changes = write_content(
        plan(tmp_path / "{student_group}"), workspace, TARGET, CLONE_URL
    )

    assert [change.path for change in changes] == ["config"]
    assert not (workspace / ".git").exists()


def test_a_directory_that_exists_but_is_empty_hands_out_nothing(
    tmp_path: Path,
) -> None:
    (tmp_path / "team-1").mkdir()

    with pytest.raises(RenderError, match="holds no files for course-team-1"):
        write_content(plan(tmp_path / "{student_group}"), tmp_path, TARGET, CLONE_URL)
