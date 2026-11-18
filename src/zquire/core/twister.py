import json
import shutil
import time
from pathlib import Path

from zquire.adapters import serial_port
from zquire.adapters.store import prepare_state_dir
from zquire.adapters.west import run_west
from zquire.core import profiles
from zquire.core.context import Context
from zquire.core.diagnostics import diagnostics
from zquire.core.serial import pick_port
from zquire.core.workspace import Workspace
from zquire.errors import ZquireError

EXCERPT_LINES = 40
LOG_LINES = 30
_COUNTED = {
    "passed": "passed",
    "failed": "failed",
    "error": "error",
    "skipped": "skipped",
    "not run": "built_only",
}
_FAILED = ("failed", "error")
# The reasons Twister gives a suite whose build failed, before any detail it appends.
_BUILD_FAILURES = ("Build failure", "CMake build failure")


def _platform(workspace: Workspace, platform: str | None) -> str:
    if platform is not None:
        return platform
    name = profiles.active_profile(workspace)
    if name is None:
        raise ZquireError(
            "NO_PLATFORM",
            "No platform given, and no active profile to take a board from.",
            "Pass platform, or activate a profile with profile_activate.",
        )
    return profiles.get(profiles.load(workspace), name)["board"]


def _excerpt(suite: dict, case: dict | None) -> str:
    # Twister keeps a failed Ztest case's own output, from its START line to its FAIL line.
    log = case.get("log") if case is not None else None
    lines = (log or suite.get("log", "")).splitlines()
    return "\n".join(lines[-EXCERPT_LINES:])


def _failures(suite: dict) -> list[dict]:
    cases = [case for case in suite["testcases"] if case.get("status") in _FAILED]
    return [
        {
            "suite": suite["name"],
            "case": case["identifier"] if case is not None else None,
            "status": (case or suite)["status"],
            "reason": (case or {}).get("reason") or suite.get("reason"),
            "log_excerpt": _excerpt(suite, case),
        }
        for case in cases or [None]
    ]


def _results(report: dict, workspace: Workspace) -> dict:
    counts = dict.fromkeys(_COUNTED.values(), 0)
    failures: list[dict] = []
    build_failures: list[dict] = []
    for suite in report.get("testsuites", []):
        status = suite.get("status")
        if status in _COUNTED:
            counts[_COUNTED[status]] += 1
        if status not in _FAILED:
            continue
        reason = suite.get("reason") or ""
        if reason.startswith(_BUILD_FAILURES):
            build_failures.append(
                {
                    "suite": suite["name"],
                    "reason": reason,
                    "diagnostics": diagnostics(suite.get("log", ""), workspace.root, failed=True),
                }
            )
        else:
            failures += _failures(suite)
    return {"counts": counts, "failures": failures, "build_failures": build_failures}


def _read_report(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def twister(
    context: Context,
    paths: list[str] | None = None,
    scenarios: list[str] | None = None,
    platform: str | None = None,
    device_testing: bool = False,
    device_serial: str | None = None,
) -> dict:
    workspace = context.workspace
    paths, scenarios = paths or [], scenarios or []
    if not paths and not scenarios:
        raise ZquireError(
            "INVALID_ARGUMENT",
            "Twister needs test paths or scenario names to run.",
            "Pass paths, scenarios, or both.",
        )
    if device_serial is not None and not device_testing:
        raise ZquireError(
            "INVALID_ARGUMENT",
            "device_serial only applies to device testing.",
            "Pass device_testing true as well, or drop device_serial.",
        )
    chosen = _platform(workspace, platform)
    state = prepare_state_dir(workspace.root)
    outdir = state / "twister"
    # Twister would keep the last run beside this one as twister.1, twister.2 and so on.
    shutil.rmtree(outdir, ignore_errors=True)
    log = state / "logs" / "twister.log"
    arguments = ["twister", "-p", chosen, "-O", str(outdir)]
    for path in paths:
        arguments += ["-T", str(workspace.resolve(path))]
    for scenario in scenarios:
        arguments += ["-s", scenario]
    if device_testing:
        if device_serial is None:
            device_serial = pick_port(serial_port.usb_ports())
        arguments += ["--device-testing", "--device-serial", device_serial]
    started = time.monotonic()
    exit_code = run_west(workspace.root, arguments, log)
    duration = round(time.monotonic() - started, 3)
    report_path = outdir / "twister.json"
    report = _read_report(report_path)
    result = {
        "status": "success" if exit_code == 0 else "failure",
        "platform": chosen,
        "duration_s": duration,
        **_results(report or {}, workspace),
        "output_dir": workspace.relative(outdir),
        "report_path": workspace.relative(report_path) if report is not None else None,
        "log_path": workspace.relative(log),
        "log_excerpt": None,
    }
    if report is None:
        lines = log.read_text(errors="replace").splitlines()
        result["log_excerpt"] = "\n".join(lines[-LOG_LINES:])
    return result
