import os
import shutil
import time

import pytest
from west.commands import Verbosity

from tests.serial_device import Device, captured
from tests.workspaces import (
    build_output,
    fake_west_build,
    flash_calls,
    flash_output,
    flash_port,
    t3,
)
from zquire.core import serial
from zquire.core.context import Context
from zquire.core.flash import EXCERPT_LINES
from zquire.core.workspace import locate
from zquire.errors import ZquireError
from zquire.tools import TOOLS, invoke


@pytest.fixture
def root(tmp_path):
    root = fake_west_build(t3(tmp_path / "ws", "app"))
    (root / "app" / "src").mkdir()
    (root / "app" / "src" / "main.c").write_text("int main(void) { return 0; }\n")
    for name in ("one", "two"):
        call(root, "profile_create", name=name, application="app", board="b")
    call(root, "profile_activate", name="one")
    call(root, "build", profile="one")
    return root


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def fails(root, **arguments):
    with pytest.raises(ZquireError) as raised:
        call(root, "flash", **arguments)
    assert raised.value.message and raised.value.hint
    return raised.value


def output(root, text, exit_code=0):
    (root / "fake-build" / "flash-output.log").write_text(text)
    (root / "fake-build" / "flash-exit_code").write_text(str(exit_code))


def modify(path):
    path.write_text("changed\n")
    later = time.time_ns() + 10**10
    os.utime(path, ns=(later, later))


def test_flash_tool_is_registered():
    assert "flash" in TOOLS


def test_success(root):
    result = call(root, "flash")
    assert {key: result[key] for key in ("profile", "status", "runner", "build_dir")} == {
        "profile": "one",
        "status": "success",
        "runner": "openocd",
        "build_dir": "app/build/one",
    }
    assert result["warnings"] == []
    assert result["log_path"] == ".zquire/logs/one-flash.log"
    assert (root / result["log_path"]).read_text().endswith("shutdown command invoked\n")


def test_west_flash_runs_verbose_without_rebuilding(root):
    call(root, "flash")
    assert flash_calls(root) == [
        {
            "build_dir": str(root / "app" / "build" / "one"),
            "runner": None,
            "no_rebuild": True,
            "verbosity": Verbosity.DBG,
        }
    ]


def test_runner_override(root):
    output(root, "-- west flash: using runner jlink\n")
    result = call(root, "flash", runner="jlink")
    assert flash_calls(root)[0]["runner"] == "jlink"
    assert result["runner"] == "jlink"


def test_runner_reported_by_west_wins(root):
    assert call(root, "flash", runner="jlink")["runner"] == "openocd"


@pytest.mark.parametrize(("runner", "expected"), [(None, None), ("jlink", "jlink")])
def test_runner_west_did_not_report(root, runner, expected):
    output(root, "FATAL ERROR: no runners.yaml found\n", exit_code=1)
    arguments = {} if runner is None else {"runner": runner}
    assert call(root, "flash", **arguments)["runner"] == expected


def test_colour_codes_are_removed(root):
    output(root, "\x1b[92m-- west flash: using runner nrfutil\x1b[0m\ndone\n")
    result = call(root, "flash")
    assert (result["runner"], result["log_excerpt"]) == (
        "nrfutil",
        "-- west flash: using runner nrfutil\ndone",
    )


@pytest.mark.parametrize("total", [EXCERPT_LINES - 1, EXCERPT_LINES, EXCERPT_LINES + 1])
def test_excerpt_is_the_last_lines(root, total):
    lines = [f"line {n}" for n in range(1, total + 1)]
    output(root, "".join(f"{line}\n" for line in lines))
    assert call(root, "flash")["log_excerpt"].splitlines() == lines[-EXCERPT_LINES:]


def test_duration_is_measured(root):
    started = time.monotonic()
    duration = call(root, "flash")["duration_s"]
    assert 0 < duration <= time.monotonic() - started


def test_failure_that_is_not_a_missing_device(root):
    flash_output(root, "flash-missing-tool")
    result = call(root, "flash")
    assert (result["status"], result["runner"]) == ("failure", "stm32cubeprogrammer")
    assert "STM32_Programmer_CLI not found" in result["log_excerpt"]


@pytest.mark.parametrize(
    ("log", "message"),
    [
        ("flash-openocd", "Error: open failed"),
        (
            "flash-jlink",
            "Connecting to J-Link via USB...FAILED: Cannot connect to the probe/programmer.",
        ),
    ],
)
def test_no_device_from_recorded_runners(root, log, message):
    flash_output(root, log)
    error = fails(root)
    assert (error.code, error.message) == ("NO_DEVICE", f"No probe or board was found: {message}")
    assert ".zquire/logs/one-flash.log" in error.hint


def test_no_device_from_nordic_runners(root):
    output(root, "FATAL ERROR: There are no boards connected.\n", exit_code=1)
    assert fails(root).message.endswith("There are no boards connected.")


def test_device_message_in_a_successful_flash_is_not_an_error(root):
    output(root, "Error: open failed\nretrying\nok\n")
    assert call(root, "flash")["status"] == "success"


def test_named_profile(root):
    call(root, "build", profile="two")
    result = call(root, "flash", profile="two")
    assert (result["profile"], result["build_dir"]) == ("two", "app/build/two")
    assert flash_calls(root)[0]["build_dir"] == str(root / "app" / "build" / "two")


def test_unknown_profile(root):
    assert fails(root, profile="nope").code == "PROFILE_NOT_FOUND"
    assert flash_calls(root) == []


def test_no_active_profile(tmp_path):
    root = fake_west_build(t3(tmp_path / "ws", "app"))
    assert fails(root).code == "NO_BUILD"
    assert flash_calls(root) == []
    assert not (root / ".zquire").exists()


def test_profile_never_built(root):
    error = fails(root, profile="two")
    assert (error.code, flash_calls(root)) == ("NO_BUILD", [])
    assert "'two'" in error.message


def test_only_failed_builds(root):
    build_output(root, "compiler")
    call(root, "build", profile="two")
    assert fails(root, profile="two").code == "NO_BUILD"


def test_build_directory_removed(root):
    shutil.rmtree(root / "app" / "build" / "one")
    assert fails(root).code == "NO_BUILD"
    assert flash_calls(root) == []


def test_failed_rebuild_flashes_the_last_success(root):
    build_output(root, "compiler")
    call(root, "build", profile="one")
    result = call(root, "flash")
    assert (result["status"], result["warnings"]) == ("success", [])


def test_stale_build_is_flashed_with_a_warning(root):
    modify(root / "app" / "src" / "main.c")
    result = call(root, "flash")
    assert result["status"] == "success"
    assert [warning["code"] for warning in result["warnings"]] == ["stale_build"]
    assert "'one'" in result["warnings"][0]["message"]


def test_stale_build_refused_when_fresh_required(root):
    modify(root / "app" / "src" / "main.c")
    error = fails(root, require_fresh=True)
    assert error.code == "STALE_BUILD"
    assert flash_calls(root) == []


def test_fresh_build_with_fresh_required(root):
    assert call(root, "flash", require_fresh=True)["warnings"] == []


def test_no_build_is_run(root):
    calls = (root / "fake-build" / "calls.jsonl").read_text()
    call(root, "flash")
    assert (root / "fake-build" / "calls.jsonl").read_text() == calls


def test_profile_delete_removes_the_flash_log(root):
    call(root, "build", profile="two")
    call(root, "flash", profile="two")
    call(root, "profile_delete", name="two")
    assert not (root / ".zquire" / "logs" / "two-flash.log").exists()


def test_log_that_is_not_utf8(root):
    (root / "fake-build" / "flash-output.log").write_bytes(b"probe \xff\nok\n")
    assert call(root, "flash")["log_excerpt"] == "probe �\nok"


def default_runner(root, runner, profile="one"):
    runners = root / "app" / "build" / profile / "zephyr" / "runners.yaml"
    runners.parent.mkdir(parents=True, exist_ok=True)
    runners.write_text(f"runners:\n- {runner}\n- jlink\n\n# Default\nflash-runner: {runner}\n")


@pytest.mark.parametrize("runner", ["qemu", "native", "arc-nsim"])
def test_emulator_default_runner_is_refused(root, runner):
    default_runner(root, runner)
    error = fails(root)
    assert error.code == "NOT_FLASHABLE"
    assert f"'{runner}'" in error.message
    assert flash_calls(root) == []


def test_emulator_runner_override_is_refused(root):
    default_runner(root, "openocd")
    assert fails(root, runner="qemu").code == "NOT_FLASHABLE"


def test_hardware_runner_override_on_an_emulator_build(root):
    default_runner(root, "qemu")
    assert call(root, "flash", runner="jlink")["status"] == "success"


def test_hardware_default_runner(root):
    default_runner(root, "openocd")
    assert call(root, "flash")["status"] == "success"


def test_runners_yaml_without_a_flash_runner(root):
    default_runner(root, "qemu")
    runners = root / "app" / "build" / "one" / "zephyr" / "runners.yaml"
    runners.write_text("runners:\n- qemu\n")
    assert call(root, "flash")["status"] == "success"


@pytest.fixture
def console(root, tmp_path, device):
    """A capture open on the board's console, a link to the device as USB names are."""
    link = tmp_path / "console"
    link.symlink_to(device.port)
    call(root, "serial_open", port=str(link))
    yield link
    call(root, "serial_close")


def entries(root, cursor=0):
    return [(e["kind"], e["text"]) for e in call(root, "serial_read", cursor=cursor)["lines"]]


def test_flash_releases_the_capture_port(root, console, device):
    device.print("old firmware\n")
    captured(lambda tool, **a: call(root, tool, **a), 1)
    flash_port(root, console, device.port, delay=0)
    result = call(root, "flash")
    assert (result["status"], result["warnings"]) == ("success", [])
    assert flash_calls(root)[0]["port_free"] is True
    assert entries(root) == [("rx", "old firmware"), ("flash", "Port released for flashing.")]
    device.print("new firmware\n")
    captured(lambda tool, **a: call(root, tool, **a), 3)
    assert entries(root, cursor=2) == [("rx", "new firmware")]


def test_flash_waits_for_the_console_to_re_enumerate(root, console, device):
    again = Device()
    try:
        flash_port(root, console, again.port, delay=1)
        assert call(root, "flash")["warnings"] == []
        again.print("*** Booting Zephyr OS build v4.4.0 ***\n")
        captured(lambda tool, **a: call(root, tool, **a), 2)
        assert entries(root) == [
            ("flash", "Port released for flashing."),
            ("rx", "*** Booting Zephyr OS build v4.4.0 ***"),
        ]
    finally:
        again.close()


def test_console_that_does_not_come_back(root, console, monkeypatch):
    monkeypatch.setattr(serial, "RESUME_TIMEOUT_S", 0.3)
    flash_port(root, console, None)
    started = time.monotonic()
    result = call(root, "flash")
    assert time.monotonic() - started < 5
    assert result["status"] == "success"
    assert result["warnings"] == [
        {
            "code": "serial_not_reopened",
            "message": "The serial capture could not reopen its port within 0.3 s of "
            "flashing, and keeps trying.",
        }
    ]
    assert entries(root) == [
        ("flash", "Port released for flashing."),
        ("disconnected", f"{console} did not come back within 0.3 s of flashing."),
    ]


def test_stale_warning_and_serial_warning_together(root, console, monkeypatch):
    monkeypatch.setattr(serial, "RESUME_TIMEOUT_S", 0.1)
    modify(root / "app" / "src" / "main.c")
    flash_port(root, console, None)
    codes = [w["code"] for w in call(root, "flash")["warnings"]]
    assert codes == ["stale_build", "serial_not_reopened"]


def test_failed_flash_reopens_the_port(root, console, device):
    flash_output(root, "flash-openocd")
    assert fails(root).code == "NO_DEVICE"
    assert entries(root)[-1][0] == "flash"
    assert call(root, "serial_write", text="help")["sent"] == "help\r\n"


@pytest.mark.parametrize(
    "refusal",
    [
        lambda root: shutil.rmtree(root / "app" / "build" / "one"),
        lambda root: default_runner(root, "qemu"),
        lambda root: modify(root / "app" / "src" / "main.c"),
    ],
    ids=["no-build", "emulator", "stale"],
)
def test_refused_flash_keeps_the_port(root, console, refusal):
    refusal(root)
    fails(root, require_fresh=True)
    assert entries(root) == []


def test_release_and_resume_without_a_capture(root):
    assert serial.release(locate(root)) is False
    assert serial.resume(locate(root)) is True
