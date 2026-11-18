import json

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.workspaces import (
    fake_west_build,
    fake_zview,
    t3,
    zview_build,
    zview_dump,
    zview_heap,
    zview_thread,
)
from zquire.core.context import Context
from zquire.core.runtime_stats import REQUIRED
from zquire.core.workspace import locate
from zquire.errors import ZquireError
from zquire.tools import TOOLS, invoke

scenarios("features/runtime_stats_filters.feature")

EVERY = (*REQUIRED, "CONFIG_THREAD_RUNTIME_STATS", "CONFIG_SYS_HEAP_RUNTIME_STATS")


@pytest.fixture
def root(tmp_path):
    root = fake_zview(fake_west_build(t3(tmp_path / "ws", "app")))
    result = call(root, "build", application="app", board="nrf52840dk/nrf52840")
    zview_build(root, root / result["build_dir"], "".join(f"{o}=y\n" for o in EVERY))
    zview_dump(root, [zview_thread("main")], [zview_heap("app_heap")])
    return root


@pytest.fixture
def outcome():
    return {}


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


@given("the prerequisites are met")
def prerequisites_met(root):
    pass


@given(parsers.re(r"threads (?P<names>.+) exist"))
def threads_exist(root, names):
    found = [name.strip('" ') for name in names.replace(" and ", ", ").split(",")]
    zview_dump(root, [zview_thread(name) for name in found], [zview_heap("app_heap")])


@when(
    parsers.re(r'the agent calls "runtime_stats" with (?P<key>include|threads|heaps) (?P<value>.+)')
)
def agent_calls(root, outcome, key, value):
    try:
        outcome["result"] = call(root, "runtime_stats", **{key: json.loads(value)})
    except ZquireError as error:
        outcome["error"] = error


@then("the result contains threads")
def contains_threads(outcome):
    assert [t["name"] for t in outcome["result"]["threads"]] == ["main"]


@then("the result contains no heaps")
def no_heaps(outcome):
    assert "heaps" not in outcome["result"]


@then(parsers.parse('exactly one thread "{name}" is returned'))
@then(parsers.parse('thread "{name}" is returned'))
def one_thread(outcome, name):
    assert [t["name"] for t in outcome["result"]["threads"]] == [name]


@then(parsers.parse('not_found lists "{name}"'))
def not_found(outcome, name):
    assert outcome["result"]["not_found"] == [name]


@then(parsers.parse('the call fails with error "{code}"'))
def fails_with(outcome, code):
    assert outcome["error"].code == code
