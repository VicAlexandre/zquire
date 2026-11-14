import pytest
from pytest_bdd import given, parsers, scenario, then, when

from tests.workspaces import t3
from zquire.core.context import Context
from zquire.core.workspace import locate
from zquire.errors import ZquireError
from zquire.tools import TOOLS, invoke

FEATURE = "features/profiles.feature"


@scenario(FEATURE, "Derive a debug profile from an existing one")
def test_derive_a_debug_profile():
    pass


@scenario(FEATURE, "Shared build directory")
def test_shared_build_directory():
    pass


@scenario(FEATURE, "Invalid profile name")
def test_invalid_profile_name():
    pass


@scenario(FEATURE, "Delete the active profile")
def test_delete_the_active_profile():
    pass


@scenario(FEATURE, "Board taken from west config")
def test_board_from_west_config():
    pass


@scenario("features/workspace.feature", "Active target persists across restarts")
def test_active_profile_persists():
    pass


@pytest.fixture
def root(tmp_path):
    return t3(tmp_path / "ws", "app")


@pytest.fixture
def outcome():
    return {}


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def attempt(outcome, root, tool, **arguments):
    try:
        outcome["result"] = call(root, tool, **arguments)
    except ZquireError as error:
        outcome["error"] = error


@given(parsers.parse('profile "{name}" builds "{application}" for "{board}"'))
def profile_builds(root, name, application, board):
    call(root, "profile_create", name=name, application=application, board=board)


@given(parsers.parse('profile "{name}" uses build directory "{build_dir}"'))
def profile_uses_build_dir(root, name, build_dir):
    call(root, "profile_create", name=name, application="app", board="b", build_dir=build_dir)


@given(parsers.re(r'the agent activated build profile "(?P<name>[^"]+)"'))
@given(parsers.re(r'the active profile is "(?P<name>[^"]+)"'))
def active_profile(root, name):
    call(root, "profile_create", name=name, application="app", board="b")
    call(root, "profile_activate", name=name)


@given(parsers.parse('"west config build.board" is "{board}" at the local level'))
def local_board(root, board):
    with (root / ".west" / "config").open("a") as config:
        config.write(f"\n[build]\nboard = {board}\n")


@when(
    parsers.parse(
        'the agent calls "profile_create" with name "{name}", from "{source}" '
        'and extra conf file "{conf}"'
    )
)
def create_from(root, outcome, name, source, conf):
    attempt(outcome, root, "profile_create", name=name, conf_files=[conf], **{"from": source})


@when(parsers.parse('the agent creates profile "{name}" with build directory "{build_dir}"'))
def create_with_build_dir(root, outcome, name, build_dir):
    attempt(
        outcome,
        root,
        "profile_create",
        name=name,
        application="app",
        board="b",
        build_dir=build_dir,
    )


@when(parsers.parse('the agent creates a profile named "{name}"'))
def create_named(root, outcome, name):
    attempt(outcome, root, "profile_create", name=name, application="app", board="b")


@when(parsers.parse('the agent calls "profile_delete" for "{name}"'))
def delete(root, outcome, name):
    attempt(outcome, root, "profile_delete", name=name)


@when(
    parsers.parse(
        'the agent calls "profile_create" with name "{name}", application "{application}" '
        "and no board"
    )
)
def create_without_board(root, outcome, name, application):
    attempt(outcome, root, "profile_create", name=name, application=application)


@when("zquire is restarted")
def restarted():
    """Each call locates the workspace afresh, which is what a restart does."""


@when('the agent calls "status"')
def status(root, outcome):
    attempt(outcome, root, "status")


def profile(root, name):
    return {p["name"]: p for p in call(root, "profile_list")["profiles"]}[name]


@then(parsers.parse('profile "{name}" has the same application and board as "{source}"'))
def same_application_and_board(root, name, source):
    derived, original = profile(root, name), profile(root, source)
    assert (derived["application"], derived["board"]) == (
        original["application"],
        original["board"],
    )


@then(parsers.parse('profile "{name}" adds "{conf}" to EXTRA_CONF_FILE'))
def adds_conf(root, name, conf):
    assert conf in profile(root, name)["conf_files"]


@then(parsers.parse('its build directory is "{build_dir}"'))
def build_dir_is(outcome, build_dir):
    assert outcome["result"]["profile"]["build_dir"] == build_dir


@then(parsers.parse('the call fails with error "{code}"'))
def fails_with(outcome, code):
    assert outcome["error"].code == code


@then(parsers.parse('profile "{name}" uses board "{board}"'))
def uses_board(root, name, board):
    assert profile(root, name)["board"] == board


@then("the result says the board came from west config, local level")
def board_from_local_config(outcome):
    assert {"setting": "board", "source": "west config", "level": "local"} in outcome["result"][
        "defaults_applied"
    ]


@then(parsers.parse('the active build profile is "{name}"'))
def active_build_profile_is(outcome, name):
    assert outcome["result"]["workspace"]["active_profile"] == name
