import os
import time

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.workspaces import fake_west_build, flash_calls, flash_output, t3
from zquire.core.context import Context
from zquire.core.workspace import locate
from zquire.errors import ZquireError
from zquire.tools import TOOLS, invoke

scenarios("features/flash.feature")


@pytest.fixture
def root(tmp_path):
    return fake_west_build(t3(tmp_path / "ws", "app"))


@pytest.fixture
def outcome():
    return {}


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def built(root):
    (root / "app" / "src").mkdir()
    (root / "app" / "src" / "main.c").write_text("int main(void) { return 0; }\n")
    call(root, "build", application="app", board="stm32f4_disco")


@given("an active, up-to-date build")
def up_to_date_build(root):
    built(root)


@given("a board connected via its default runner")
def board_connected(root):
    flash_output(root, "flash-success")


@given("no active build directory")
def no_build(root):
    call(root, "profile_create", name="bench-1", application="app", board="b")
    call(root, "profile_activate", name="bench-1")


@given(parsers.parse('"{path}" was modified after the last build'))
def modified_after_build(root, path):
    built(root)
    target = root / "app" / path
    target.write_text("changed\n")
    later = time.time_ns() + 10**10
    os.utime(target, ns=(later, later))


@given("no board is connected")
def no_board(root):
    built(root)
    flash_output(root, "flash-openocd")


@when(parsers.re(r'the agent calls "flash"(?P<fresh> with require_fresh true)?'))
def agent_flashes(root, outcome, fresh):
    try:
        outcome["result"] = call(root, "flash", **({"require_fresh": True} if fresh else {}))
    except ZquireError as error:
        outcome["error"] = error


@then(parsers.parse('the status is "{status}"'))
def status_is(outcome, status):
    assert outcome["result"]["status"] == status


@then("the result names the runner used")
def names_runner(outcome):
    assert outcome["result"]["runner"] == "openocd"


@then(parsers.parse('the call fails with error "{code}"'))
def fails_with(outcome, code):
    assert outcome["error"].code == code


@then("west is not invoked")
def west_not_invoked(root):
    assert flash_calls(root) == []


@then(parsers.parse('the result contains a "{code}" warning'))
def contains_warning(outcome, code):
    assert code in [warning["code"] for warning in outcome["result"]["warnings"]]


@then("the error includes the runner's message")
def includes_runner_message(outcome):
    assert "Error: open failed" in outcome["error"].message
