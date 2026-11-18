import json

import pytest

from tests.workspaces import (
    LOGS,
    fake_west_build,
    t3,
    twister_calls,
    twister_report,
    twister_suite,
)
from zquire import cli
from zquire.adapters import serial_port
from zquire.core.context import Context
from zquire.core.twister import EXCERPT_LINES, LOG_LINES
from zquire.core.workspace import locate
from zquire.errors import ZquireError
from zquire.tools import TOOLS, invoke


@pytest.fixture
def root(tmp_path):
    root = fake_west_build(t3(tmp_path / "ws", "app"))
    (root / "app" / "tests" / "parser").mkdir(parents=True)
    return root


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def run(root, **arguments):
    defaults = {"paths": ["app/tests/parser"], "platform": "native_sim"}
    return call(root, "twister", **defaults | arguments)


def fails(root, **arguments):
    with pytest.raises(ZquireError) as error:
        call(root, "twister", **arguments)
    return error.value


def lines(count, prefix="line"):
    return "\n".join(f"{prefix} {n}" for n in range(1, count + 1))


def test_runs_paths_from_the_workspace_root(root):
    run(root, paths=["app/tests/parser", "app/tests/other"])
    (made,) = twister_calls(root)
    assert made["testsuite_roots"] == [
        str(root / "app" / "tests" / "parser"),
        str(root / "app" / "tests" / "other"),
    ]
    assert (made["scenarios"], made["device_testing"], made["device_serial"]) == ([], False, None)
    assert made["outdir"] == str(root / ".zquire" / "twister")


def test_runs_scenarios(root):
    call(root, "twister", scenarios=["parser.default", "parser.big"], platform="native_sim")
    (made,) = twister_calls(root)
    assert (made["testsuite_roots"], made["scenarios"]) == ([], ["parser.default", "parser.big"])


def test_runs_paths_and_scenarios_together(root):
    run(root, scenarios=["parser.default"])
    (made,) = twister_calls(root)
    assert (len(made["testsuite_roots"]), made["scenarios"]) == (1, ["parser.default"])


@pytest.mark.parametrize(
    "arguments", [{}, {"paths": []}, {"scenarios": []}, {"paths": [], "scenarios": []}]
)
def test_needs_paths_or_scenarios(root, arguments):
    assert fails(root, platform="native_sim", **arguments).code == "INVALID_ARGUMENT"
    assert twister_calls(root) == []


def test_platform_defaults_to_the_active_profiles_board(root):
    call(root, "profile_create", name="dk", application="app", board="nrf52840dk/nrf52840")
    call(root, "profile_activate", name="dk")
    result = call(root, "twister", paths=["app/tests/parser"])
    assert result["platform"] == twister_calls(root)[0]["platform"] == "nrf52840dk/nrf52840"


def test_platform_overrides_the_active_profile(root):
    call(root, "profile_create", name="dk", application="app", board="nrf52840dk/nrf52840")
    call(root, "profile_activate", name="dk")
    assert run(root)["platform"] == twister_calls(root)[0]["platform"] == "native_sim"


def test_no_platform_and_no_active_profile(root):
    error = fails(root, paths=["app/tests/parser"])
    assert error.code == "NO_PLATFORM"
    assert twister_calls(root) == []


def test_device_testing_on_a_given_port(root):
    run(root, device_testing=True, device_serial="/dev/ttyACM3")
    made = twister_calls(root)[0]
    assert (made["device_testing"], made["device_serial"]) == (True, "/dev/ttyACM3")


def test_device_testing_detects_the_port(root, monkeypatch):
    found = [serial_port.Candidate("/dev/ttyACM0", "J-Link")]
    monkeypatch.setattr(serial_port, "usb_ports", lambda: found)
    run(root, device_testing=True)
    assert twister_calls(root)[0]["device_serial"] == "/dev/ttyACM0"


@pytest.mark.parametrize(
    "found, code",
    [
        ([], "PORT_NOT_FOUND"),
        ([serial_port.Candidate(f"/dev/ttyACM{n}", "J-Link") for n in (0, 1)], "PORT_AMBIGUOUS"),
    ],
)
def test_device_testing_without_one_port(root, monkeypatch, found, code):
    monkeypatch.setattr(serial_port, "usb_ports", lambda: found)
    assert fails(root, paths=["app"], platform="b", device_testing=True).code == code
    assert twister_calls(root) == []


@pytest.mark.parametrize("device_testing", [None, False])
def test_device_serial_needs_device_testing(root, device_testing):
    arguments = {"paths": ["app"], "platform": "b", "device_serial": "/dev/ttyACM0"}
    if device_testing is not None:
        arguments["device_testing"] = device_testing
    assert fails(root, **arguments).code == "INVALID_ARGUMENT"
    assert twister_calls(root) == []


def test_reports_output_locations(root):
    result = run(root)
    assert result["output_dir"] == ".zquire/twister"
    assert result["report_path"] == ".zquire/twister/twister.json"
    assert result["log_path"] == ".zquire/logs/twister.log"
    assert result["log_excerpt"] is None
    assert json.loads((root / result["report_path"]).read_text())["testsuites"] == []


def test_logs_twisters_output(root):
    twister_report(root, [], output="INFO    - Total complete:    1/   1  100%\n")
    result = run(root)
    assert "Total complete" in (root / result["log_path"]).read_text()


def test_success_and_failure_follow_the_exit_code(root):
    twister_report(root, [twister_suite("a.default", "passed")], exit_code=0)
    assert run(root)["status"] == "success"
    twister_report(root, [twister_suite("a.default", "passed")], exit_code=1)
    assert run(root)["status"] == "failure"


def test_reports_duration(root):
    assert 0 < run(root)["duration_s"] < 60


def test_counts_suites_by_status(root):
    statuses = ["passed", "passed", "failed", "error", "skipped", "not run", "filtered", None]
    twister_report(root, [twister_suite(f"s{n}.default", s) for n, s in enumerate(statuses)])
    counts = run(root)["counts"]
    assert counts == {"passed": 2, "failed": 1, "error": 1, "skipped": 1, "built_only": 1}


def test_no_report_keeps_the_log_tail(root):
    twister_report(root, None, output=lines(LOG_LINES + 5) + "\n", exit_code=2)
    result = run(root)
    assert (result["status"], result["report_path"]) == ("failure", None)
    assert result["log_excerpt"] == "\n".join(lines(LOG_LINES + 5).splitlines()[-LOG_LINES:])
    assert result["counts"] == dict.fromkeys(result["counts"], 0)
    assert (result["failures"], result["build_failures"]) == ([], [])


def test_log_with_invalid_utf8(root):
    twister_report(root, None, exit_code=1)
    (root / "fake-build" / "twister-output.log").write_bytes(b"ERROR   - bad \xff byte\n")
    assert run(root)["log_excerpt"] == "ERROR   - bad \ufffd byte"


def test_a_short_log_is_kept_whole(root):
    twister_report(root, None, output="ERROR   - No tests to run\n", exit_code=1)
    assert run(root)["log_excerpt"] == "ERROR   - No tests to run"


def test_an_unreadable_report_counts_as_none(root):
    twister_report(root, [])
    (root / "fake-build" / "twister.json").write_text('{"testsuites": [')
    assert run(root)["report_path"] is None


def test_a_previous_report_is_not_reused(root):
    twister_report(root, [twister_suite("a.default", "passed")])
    run(root)
    twister_report(root, None, exit_code=1)
    result = run(root)
    assert (result["report_path"], result["counts"]["passed"]) == (None, 0)


def test_failed_case_excerpt_is_its_own_output(root):
    suite = twister_suite("a.default", "failed", [("a.default.a.one", "failed")])
    suite["testcases"][0]["log"] = lines(5, "case")
    suite["log"] = lines(5, "suite")
    twister_report(root, [suite])
    (failure,) = run(root)["failures"]
    assert failure == {
        "suite": "a.default",
        "case": "a.default.a.one",
        "status": "failed",
        "reason": None,
        "log_excerpt": lines(5, "case"),
    }


def test_excerpt_keeps_the_lines_ending_at_the_failure(root):
    suite = twister_suite("a.default", "failed", [("a.default.a.one", "failed")])
    suite["testcases"][0]["log"] = lines(EXCERPT_LINES + 1)
    twister_report(root, [suite])
    excerpt = run(root)["failures"][0]["log_excerpt"].splitlines()
    assert excerpt == lines(EXCERPT_LINES + 1).splitlines()[1:]


@pytest.mark.parametrize("case_log", [None, ""])
def test_case_without_output_takes_the_suite_log(root, case_log):
    suite = twister_suite("a.default", "failed", [("a.default.a.one", "failed")])
    if case_log is not None:
        suite["testcases"][0]["log"] = case_log
    suite["log"] = lines(EXCERPT_LINES + 3, "suite")
    twister_report(root, [suite])
    excerpt = run(root)["failures"][0]["log_excerpt"]
    assert excerpt == "\n".join(lines(EXCERPT_LINES + 3, "suite").splitlines()[-EXCERPT_LINES:])


def test_suite_without_a_log(root):
    twister_report(root, [twister_suite("a.default", "failed", [("a.default.a.one", "failed")])])
    assert run(root)["failures"][0]["log_excerpt"] == ""


def test_each_failed_or_errored_case_is_listed(root):
    cases = [
        ("a.default.a.one", "passed"),
        ("a.default.a.two", "failed"),
        ("a.default.a.three", "error"),
        ("a.default.a.four", "blocked"),
        ("a.default.a.five", "skipped"),
    ]
    twister_report(root, [twister_suite("a.default", "failed", cases)])
    failures = run(root)["failures"]
    assert [(f["case"], f["status"]) for f in failures] == [
        ("a.default.a.two", "failed"),
        ("a.default.a.three", "error"),
    ]


def test_case_reason_comes_before_the_suite_reason(root):
    cases = [("a.default.a.one", "failed"), ("a.default.a.two", "failed")]
    suite = twister_suite("a.default", "failed", cases, reason="Testsuite failed")
    suite["testcases"][0]["reason"] = "Timeout"
    twister_report(root, [suite])
    assert [f["reason"] for f in run(root)["failures"]] == ["Timeout", "Testsuite failed"]


@pytest.mark.parametrize("status", ["failed", "error"])
def test_suite_failing_outside_any_case(root, status):
    suite = twister_suite(
        "a.default", status, [("a.default.a.one", "blocked")], reason="Timeout", log=lines(3)
    )
    twister_report(root, [suite])
    (failure,) = run(root)["failures"]
    assert failure == {
        "suite": "a.default",
        "case": None,
        "status": status,
        "reason": "Timeout",
        "log_excerpt": lines(3),
    }


def test_passing_suites_are_not_failures(root):
    suite = twister_suite("a.default", "passed", [("a.default.a.one", "failed")], log="x")
    twister_report(root, [suite, twister_suite("b.default", "skipped", reason="slow")])
    result = run(root)
    assert (result["failures"], result["build_failures"]) == ([], [])


@pytest.mark.parametrize(
    "reason",
    [
        "Build failure",
        "Build failure - app/src/main.c:7: error: 'x' undeclared",
        "CMake build failure - CMake Error at CMakeLists.txt:3",
    ],
)
def test_build_failure_returns_build_diagnostics(root, reason):
    log = (LOGS / "compiler.log").read_text()
    twister_report(root, [twister_suite("a.default", "error", reason=reason, log=log)])
    result = run(root)
    (failure,) = result["build_failures"]
    assert (failure["suite"], failure["reason"], result["failures"]) == ("a.default", reason, [])
    compiler = [d for d in failure["diagnostics"] if d["category"] == "compiler"]
    assert compiler and compiler[0]["file"] == "app/src/main.c"


def test_build_failure_without_diagnostics(root):
    suite = twister_suite("a.default", "error", reason="Build failure", log=lines(3))
    twister_report(root, [suite])
    (diagnostic,) = run(root)["build_failures"][0]["diagnostics"]
    assert (diagnostic["category"], diagnostic["log_excerpt"]) == ("unknown", lines(3))


def test_build_failure_without_a_log(root):
    twister_report(root, [twister_suite("a.default", "error", reason="Build failure")])
    (diagnostic,) = run(root)["build_failures"][0]["diagnostics"]
    assert (diagnostic["category"], diagnostic["log_excerpt"]) == ("unknown", "")


def test_failures_from_every_suite(root):
    suites = [
        twister_suite("a.default", "failed", [("a.default.a.one", "failed")]),
        twister_suite("b.default", "error", reason="Build failure"),
        twister_suite("c.default", "failed", [("c.default.c.one", "failed")]),
        twister_suite("d.default", "error", reason="Build failure"),
    ]
    twister_report(root, suites)
    result = run(root)
    assert [f["suite"] for f in result["failures"]] == ["a.default", "c.default"]
    assert [f["suite"] for f in result["build_failures"]] == ["b.default", "d.default"]


@pytest.mark.parametrize("reason", [None, "Execution failure", "a Build failure"])
def test_other_errors_are_not_build_failures(root, reason):
    suite = twister_suite("a.default", "error", log="x")
    if reason is not None:
        suite["reason"] = reason
    twister_report(root, [suite])
    result = run(root)
    assert (len(result["failures"]), result["build_failures"]) == (1, [])
    assert result["failures"][0]["reason"] == reason


def test_cli_takes_paths_as_json(root, capsys):
    arguments = ["--paths", '["app/tests/parser"]', "--platform", "native_sim"]
    assert cli.main(["--workspace", str(root), "twister", *arguments]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "success"
