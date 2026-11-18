import time
from pathlib import Path

import pytest

from tests.serial_device import Device, captured
from tests.workspaces import (
    fake_west_build,
    t3,
    twister_calls,
    twister_hang,
    twister_port,
    twister_report,
    twister_suite,
)
from zquire.adapters import serial_port, west
from zquire.core import serial
from zquire.core import twister as twister_module
from zquire.core.context import Context
from zquire.core.twister import DEFAULT_TIMEOUT_S
from zquire.core.workspace import locate
from zquire.tools import TOOLS, invoke


@pytest.fixture
def root(tmp_path):
    return fake_west_build(t3(tmp_path / "ws", "app"))


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def run(root, **arguments):
    defaults = {"paths": ["app"], "platform": "nrf52840dk/nrf52840"}
    return call(root, "twister", **defaults | arguments)


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


def resumed(root, device):
    count = len(entries(root)) + 1
    device.print("after the run\n")
    captured(lambda tool, **a: call(root, tool, **a), count)
    assert entries(root)[-1] == ("rx", "after the run")


def test_device_testing_releases_the_capture_port(root, console, device):
    twister_port(root, console, device.port, delay=0)
    result = run(root, device_testing=True)
    made = twister_calls(root)[0]
    assert (made["device_serial"], made["port_free"]) == (str(console), True)
    assert (result["status"], result["warnings"]) == ("success", [])
    assert entries(root) == [("flash", "Port released for flashing.")]
    resumed(root, device)


def test_capture_resumes_on_the_re_enumerated_console(root, console):
    again = Device()
    try:
        twister_port(root, console, again.port, delay=1)
        assert run(root, device_testing=True)["warnings"] == []
        resumed(root, again)
    finally:
        again.close()


def test_given_port_naming_the_capture_port_is_released(root, console, device):
    twister_port(root, console, device.port, delay=0)
    run(root, device_testing=True, device_serial=device.port)
    assert twister_calls(root)[0]["port_free"] is True
    assert entries(root)[0][0] == "flash"


def test_capture_on_another_port_is_left_open(root, console, device):
    other = Device()
    try:
        run(root, device_testing=True, device_serial=other.port)
        assert twister_calls(root)[0]["device_serial"] == other.port
        assert entries(root) == []
        resumed(root, device)
    finally:
        other.close()


def test_capture_port_is_kept_without_device_testing(root, console, device):
    run(root)
    assert entries(root) == []
    resumed(root, device)


def test_device_testing_without_a_capture(root, monkeypatch):
    found = [serial_port.Candidate("/dev/ttyACM0", "J-Link")]
    monkeypatch.setattr(serial_port, "usb_ports", lambda: found)
    result = run(root, device_testing=True)
    assert (twister_calls(root)[0]["device_serial"], result["warnings"]) == ("/dev/ttyACM0", [])


def test_console_that_does_not_come_back(root, console, monkeypatch):
    monkeypatch.setattr(serial, "RESUME_TIMEOUT_S", 0.3)
    twister_port(root, console, None)
    result = run(root, device_testing=True)
    assert result["warnings"] == [
        {
            "code": "serial_not_reopened",
            "message": "The serial capture could not reopen its port within 0.3 s of "
            "device testing, and keeps trying.",
        }
    ]


def test_failed_run_resumes_the_capture(root, console, device):
    twister_report(root, [twister_suite("a.default", "failed")])
    assert run(root, device_testing=True)["status"] == "failure"
    resumed(root, device)


def test_run_that_raises_resumes_the_capture(root, console, device, monkeypatch):
    def broken(*arguments):
        raise OSError("west is gone")

    monkeypatch.setattr(twister_module, "run_west", broken)
    with pytest.raises(OSError):
        run(root, device_testing=True)
    resumed(root, device)


def gone(pid: int) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except FileNotFoundError:
            return True
        if state == "Z":
            return True
        time.sleep(0.05)
    return False


def child(root) -> int:
    return int((root / "fake-build" / "twister-child.pid").read_text())


def test_timeout_interrupts_twister_and_keeps_its_report(root):
    twister_report(root, [twister_suite("a.default", "passed"), twister_suite("b.default", None)])
    twister_hang(root, "interrupt")
    started = time.monotonic()
    result = run(root, timeout_s=2)
    assert 2 <= time.monotonic() - started < 2 + 5
    assert (result["status"], result["counts"]["passed"]) == ("timeout", 1)
    assert result["report_path"] == ".zquire/twister/twister.json"
    assert gone(child(root))


def test_twister_ignoring_the_interrupt_is_killed(root, monkeypatch):
    monkeypatch.setattr(west, "INTERRUPT_GRACE_S", 0.5)
    twister_hang(root, "ignore")
    started = time.monotonic()
    result = run(root, timeout_s=2)
    assert 2.5 <= time.monotonic() - started < 2.5 + 5
    assert (result["status"], result["report_path"]) == ("timeout", None)
    assert gone(child(root))


def test_timeout_resumes_the_capture(root, console, device):
    twister_hang(root, "interrupt")
    assert run(root, device_testing=True, timeout_s=2)["status"] == "timeout"
    resumed(root, device)


def test_default_timeout(root, monkeypatch):
    seen = []
    real = twister_module.run_west
    monkeypatch.setattr(
        twister_module,
        "run_west",
        lambda topdir, arguments, log, timeout_s: (
            seen.append(timeout_s) or real(topdir, arguments, log, timeout_s)
        ),
    )
    assert run(root)["status"] == "success"
    assert seen == [DEFAULT_TIMEOUT_S] == [30 * 60]


def test_build_and_flash_stay_in_zquires_process_group(root, monkeypatch):
    # Interrupting zquire then interrupts west and what it runs, as in a terminal.
    seen, real = [], west.subprocess.Popen
    monkeypatch.setattr(west.subprocess, "Popen", lambda *a, **k: seen.append(k) or real(*a, **k))
    call(root, "build", application="app", board="b")
    assert seen[0]["start_new_session"] is False
