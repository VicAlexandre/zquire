import time

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.serial_device import captured
from tests.workspaces import (
    LOGS,
    fake_west_build,
    t3,
    twister_calls,
    twister_hang,
    twister_port,
    twister_report,
    twister_suite,
)
from zquire.core import twister
from zquire.core.context import Context
from zquire.core.workspace import locate
from zquire.tools import TOOLS, invoke

scenarios("features/twister.feature")

SUITE = "app/tests/parser"
ASSERTION = 'parse("") not equal to -EINVAL'
# Scenario timeouts are scaled down, so a 60 s run takes 2 s.
TIME_SCALE = 1 / 30


@pytest.fixture
def root(tmp_path):
    root = fake_west_build(t3(tmp_path / "ws", "app"))
    (root / SUITE).mkdir(parents=True)
    return root


@pytest.fixture
def outcome():
    return {}


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def case_output(name: str, lines: int) -> str:
    """A Ztest case's console output from START to FAIL, as Twister keeps it."""
    body = [f"  step {n}" for n in range(lines)]
    return "\n".join(
        [f"START - {name}", *body]
        + [f"    Assertion failed at WEST_TOPDIR/{SUITE}/src/main.c:21: {name}: ({ASSERTION})"]
        + [f" FAIL - {name} in 0.001 seconds", ""]
    )


@given(parsers.parse("a test suite with {count:d} passing cases"))
def passing_suite(root, count):
    cases = [(f"parser.default.parser.case_{n}", "passed") for n in range(count)]
    twister_report(root, [twister_suite("parser.default", "passed", cases)])


@given(parsers.parse('a suite where case "{name}" fails an assertion'))
def failing_case(root, name):
    identifier = "parser.default.parser." + name.removeprefix("test_")
    cases = [("parser.default.parser.parse_digits", "passed"), (identifier, "failed")]
    suite = twister_suite("parser.default", "failed", cases, reason="Testsuite failed")
    suite["testcases"][1]["log"] = case_output(name, 60)
    suite["log"] = "*** Booting Zephyr OS build v4.4.0 ***\n" + case_output(name, 60)
    twister_report(root, [suite])


@given("a suite that does not compile")
def does_not_compile(root):
    build_log = (LOGS / "compiler.log").read_text()
    suite = twister_suite("parser.default", "error", reason="Build failure", log=build_log)
    twister_report(root, [suite])


@when(parsers.parse('the agent calls "twister" for that suite on "{platform}"'))
def run_on(root, outcome, platform):
    outcome["result"] = call(root, "twister", paths=[SUITE], platform=platform)


@when('the agent calls "twister" for that suite')
@when('the agent calls "twister" for a suite')
def run(root, outcome):
    outcome["result"] = call(root, "twister", paths=[SUITE], platform="native_sim")


@then(parsers.parse("the result shows {passed:d} suite passed and {failed:d} failed"))
def shows_counts(root, outcome, passed, failed):
    result = outcome["result"]
    assert (result["counts"]["passed"], result["counts"]["failed"]) == (passed, failed)
    assert result["status"] == "success"
    assert twister_calls(root)[0]["platform"] == "native_sim"


@then(parsers.parse('the result lists failed case "{name}"'))
def lists_failed_case(outcome, name):
    # Twister names a Ztest case after its scenario and suite, without the test_ prefix.
    cases = [failure["case"] for failure in outcome["result"]["failures"]]
    assert cases == ["parser.default.parser." + name.removeprefix("test_")]


@then("its log excerpt contains the assertion message")
def excerpt_has_assertion(outcome):
    assert ASSERTION in outcome["result"]["failures"][0]["log_excerpt"]


@then(parsers.parse("the excerpt has at most {count:d} lines"))
def excerpt_bounded(outcome, count):
    assert len(outcome["result"]["failures"][0]["log_excerpt"].splitlines()) <= count


@then(parsers.parse('the result contains a build diagnostic with category "{category}"'))
def build_diagnostic(outcome, category):
    (failure,) = outcome["result"]["build_failures"]
    assert category in [d["category"] for d in failure["diagnostics"]]


@then("the result contains the path to Twister's output directory")
def output_dir(root, outcome):
    assert (root / outcome["result"]["output_dir"]).is_dir()


@then("the result contains the path to its JSON report, and that file exists")
def report_path(root, outcome):
    assert (root / outcome["result"]["report_path"]).is_file()


@pytest.fixture
def console(root, tmp_path, device):
    link = tmp_path / "console"
    link.symlink_to(device.port)
    yield link
    call(root, "serial_close")


@given("a serial capture is open on the board")
def capture_open(root, console):
    call(root, "serial_open", port=str(console))


@when('the agent calls "twister" with device testing')
def run_on_hardware(root, console, device, outcome):
    twister_port(root, console, device.port, delay=0)
    outcome["result"] = call(root, "twister", paths=[SUITE], platform="b", device_testing=True)


@then("zquire releases the port during the run")
def port_released(root, outcome):
    assert twister_calls(root)[0]["port_free"] is True
    assert outcome["result"]["warnings"] == []


@then("capture resumes after the run")
def capture_resumes(root, device):
    device.print("after the run\n")
    captured(lambda tool, **a: call(root, tool, **a), 2)
    entries = call(root, "serial_read")["lines"]
    assert [e["kind"] for e in entries] == ["flash", "rx"]


@given("a suite that hangs")
def hangs(root):
    twister_hang(root, "interrupt")


@when(parsers.parse('the agent calls "twister" with timeout {timeout:d} s'))
def run_with_timeout(root, outcome, monkeypatch, timeout):
    real = twister.run_west
    monkeypatch.setattr(
        twister,
        "run_west",
        lambda topdir, arguments, log, timeout_s: real(
            topdir, arguments, log, timeout_s * TIME_SCALE
        ),
    )
    started = time.monotonic()
    outcome["result"] = call(root, "twister", paths=[SUITE], platform="b", timeout_s=timeout)
    outcome["elapsed"] = time.monotonic() - started


@then(parsers.parse('the status is "{status}" after about {timeout:d} s'))
def status_after(outcome, status, timeout):
    assert outcome["result"]["status"] == status
    assert timeout * TIME_SCALE <= outcome["elapsed"] < timeout * TIME_SCALE + 5
