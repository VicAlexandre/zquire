import threading
import time

import pytest
import yaml
from pytest_bdd import given, parsers, scenarios, then, when

from tests.workspaces import (
    fake_west_build,
    fake_zview,
    t3,
    zview_build,
    zview_calls,
    zview_dump,
    zview_heap,
    zview_thread,
)
from zquire.core.context import Context
from zquire.core.runtime_stats import REQUIRED
from zquire.core.workspace import locate
from zquire.errors import ZquireError
from zquire.tools import TOOLS, invoke

scenarios("features/runtime_stats.feature")

OPTIONAL = ("CONFIG_THREAD_RUNTIME_STATS", "CONFIG_SYS_HEAP_RUNTIME_STATS")


@pytest.fixture
def root(tmp_path):
    root = fake_zview(fake_west_build(t3(tmp_path / "ws", "app")))
    call(root, "build", application="app", board="nrf52840dk/nrf52840")
    configure(root, (*REQUIRED, *OPTIONAL))
    return root


@pytest.fixture
def outcome():
    return {}


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def build_dir(root):
    return root / "app" / "build" / "default"


def configure(root, options, runner="jlink"):
    config = "".join(f"{option}=y\n" for option in options)
    runners = {
        "flash-runner": runner,
        "runners": ["jlink", "pyocd", "nrfutil"],
        "args": {
            "jlink": ["--dt-flash=y", "--device=nRF52840_xxAA"],
            "pyocd": ["--target=nrf52840"],
        },
    }
    zview_build(root, build_dir(root), config, yaml.safe_dump(runners))


def stats(root, outcome, **arguments):
    try:
        outcome["result"] = call(root, "runtime_stats", **arguments)
    except ZquireError as error:
        outcome["error"] = error


@given(parsers.parse('a running board whose thread "{name}" uses {percent:d} % of its stack'))
def thread_near_overflow(root, name, percent):
    zview_dump(root, [zview_thread("main"), zview_thread(name, 1000, percent * 10)], [])


@given("the active build has all ZView prerequisites")
@given("the prerequisites are met")
def prerequisites_met(root):
    configure(root, (*REQUIRED, *OPTIONAL))


@given(parsers.parse('a heap "{name}" of {size:d} bytes with {used:d} bytes in use'))
def heap(root, name, size, used):
    zview_dump(root, [zview_thread("main")], [zview_heap(name, size, used)])


@given(parsers.parse("the active .config does not set {option}"))
def option_unset(root, option):
    configure(root, [o for o in (*REQUIRED, *OPTIONAL) if o != option])


@given(parsers.parse("the prerequisites are met but {option} is not set"))
def optional_unset(root, option):
    configure(root, [o for o in (*REQUIRED, *OPTIONAL) if o != option])
    zview_dump(root, [zview_thread("main", cpu=None), zview_thread("sensor", cpu=None)], [])


@given("the workspace manifest has no zview project")
def no_zview(root):
    commands = root / "manifest-repo" / "zquire-fake-build" / "west-commands.yml"
    entry = "      - name: zview\n        class: Zview\n"
    commands.write_text(commands.read_text().replace(entry, ""))


@given(parsers.parse('the board\'s default runner is "{runner}"'))
def default_runner(root, runner):
    configure(root, (*REQUIRED, *OPTIONAL), runner=runner)


@given("a ZView dump is in progress")
def dump_in_progress(root, outcome):
    (root / "fake-build" / "zview-delay").write_text("1")
    dump = threading.Thread(target=stats, args=(root, outcome))
    dump.start()
    deadline = time.monotonic() + 10
    while not zview_calls(root):
        assert time.monotonic() < deadline
        time.sleep(0.02)
    outcome["dump"] = dump


@when('the agent calls "runtime_stats"')
def agent_calls(root, outcome):
    stats(root, outcome)


@when(parsers.parse('the agent calls "runtime_stats" with runner "{runner}"'))
def agent_calls_with_runner(root, outcome, runner):
    stats(root, outcome, runner=runner)


@when('the agent calls "flash"')
def agent_flashes(root, outcome):
    outcome["flash"] = call(root, "flash")
    outcome["dump_alive"] = outcome["dump"].is_alive()
    outcome["dump"].join()


def thread(outcome, name):
    (found,) = [t for t in outcome["result"]["threads"] if t["name"] == name]
    return found


@then(parsers.parse('thread "{name}" has watermark {percent:d} %'))
def watermark(outcome, name, percent):
    assert thread(outcome, name)["watermark_percent"] == percent


@then(parsers.parse('thread "{name}" is flagged "{flag}"'))
def flagged(outcome, name, flag):
    assert thread(outcome, name)["flags"] == [flag]
    assert thread(outcome, "main")["flags"] == []


@then(parsers.parse('heap "{name}" has size {size:d}, used {used:d} and free {free:d}'))
def heap_usage(outcome, name, size, used, free):
    (found,) = outcome["result"]["heaps"]
    assert (found["name"], found["size"], found["used"], found["free"]) == (name, size, used, free)


@then(parsers.parse('the call fails with error "{code}"'))
def fails_with(outcome, code):
    assert outcome["error"].code == code


@then(parsers.parse('the error lists "{line}"'))
def error_lists(outcome, line):
    assert line in outcome["error"].message.splitlines()


@then("ZView is not invoked")
def not_invoked(root):
    assert zview_calls(root) == []


@then("threads are returned without CPU percent")
def without_cpu(outcome):
    assert [t["cpu_percent"] for t in outcome["result"]["threads"]] == [None, None]


@then(parsers.parse('the result warns to enable "{option}"'))
def warns(outcome, option):
    (warning,) = outcome["result"]["warnings"]
    assert warning["code"] == "option_disabled"
    assert f"{option}=y" in warning["message"]


@then("the error includes a west.yml snippet for zview")
def snippet(outcome):
    hint = outcome["error"].hint
    project = yaml.safe_load(hint[hint.index("manifest:") :])["manifest"]["projects"][0]
    assert (project["name"], project["path"]) == ("zview", "modules/tools/zview")


@then(parsers.parse('ZView is invoked with runner "{runner}"'))
def invoked_with(root, runner):
    assert zview_calls(root)[-1]["runner"] == runner


@then(parsers.parse('the flash waits until the dump finishes, or fails with "{code}" after 30 s'))
def flash_waits(outcome, code):
    assert outcome["flash"]["status"] == "success"
    assert outcome["dump_alive"] is False
    assert "threads" in outcome["result"]
