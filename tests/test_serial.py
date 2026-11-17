import os
import signal
import socket as socket_module
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from serial.tools.list_ports_common import ListPortInfo

from tests.serial_device import Device, captured
from tests.workspaces import t2
from zquire.adapters import ipc, serial_port
from zquire.core import serial
from zquire.core.context import Context
from zquire.core.serial import pick_port, socket_path
from zquire.core.workspace import locate
from zquire.errors import ZquireError
from zquire.tools import TOOLS, invoke


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def fails(root, tool, **arguments):
    with pytest.raises(ZquireError) as raised:
        call(root, tool, **arguments)
    assert raised.value.message and raised.value.hint
    return raised.value


@pytest.fixture
def root(tmp_path):
    root = t2(tmp_path / "ws")
    yield root
    call(root, "serial_close")


def test_open(root, device):
    assert call(root, "serial_open", port=device.port) == {
        "port": device.port,
        "baud": 115200,
        "buffer_lines": 50000,
        "detected": False,
        "already_open": False,
        "next_cursor": 0,
    }
    assert (root / ".zquire" / ".gitignore").is_file()


def test_open_at_a_baud_rate(root, device):
    assert call(root, "serial_open", port=device.port, baud=9600)["baud"] == 9600
    assert call(root, "serial_open")["baud"] == 9600


@pytest.mark.parametrize(
    "again",
    [{}, {"port": "same"}, {"port": "link"}, {"baud": 115200}, {"buffer_lines": 50000}],
    ids=["no-arguments", "same-port", "symlink", "same-baud", "same-size"],
)
def test_open_again_keeps_the_capture(root, device, again):
    call(root, "serial_open", port=device.port)
    device.print("a\nb\n")
    captured(lambda tool, **a: call(root, tool, **a), 2)
    again = dict(again)
    if again.get("port") == "same":
        again["port"] = device.port
    elif again.get("port") == "link":
        (root / "console").symlink_to(device.port)
        again["port"] = str(root / "console")
    assert call(root, "serial_open", **again) == {
        "port": device.port,
        "baud": 115200,
        "buffer_lines": 50000,
        "detected": False,
        "already_open": True,
        "next_cursor": 2,
    }


@pytest.mark.parametrize("other", [{"port": "other"}, {"baud": 9600}, {"buffer_lines": 10}])
def test_open_with_other_settings_while_open(root, device, other):
    call(root, "serial_open", port=device.port)
    error = fails(root, "serial_open", **other)
    assert error.code == "CAPTURE_OPEN"
    assert error.message == (
        f"A serial capture is already open on {device.port} at 115200 baud, holding 50000 lines."
    )


def test_open_with_a_buffer_size(root, device):
    assert call(root, "serial_open", port=device.port, buffer_lines=2)["buffer_lines"] == 2
    assert call(root, "serial_open")["buffer_lines"] == 2
    device.print("a\nb\nc\n")
    captured(lambda tool, **a: call(root, tool, **a), 3)
    read = call(root, "serial_read")
    assert ([e["cursor"] for e in read["lines"]], read["truncated"]) == ([2, 3], True)


def test_open_a_missing_port(root, tmp_path):
    error = fails(root, "serial_open", port=str(tmp_path / "ttyNOPE"))
    assert error.code == "PORT_NOT_FOUND"
    assert str(tmp_path / "ttyNOPE") in error.message
    assert fails(root, "serial_read").code == "NO_CAPTURE"


def test_open_a_port_held_by_another_program(root, device):
    held = serial_port.open_port(device.port, 115200)
    try:
        error = fails(root, "serial_open", port=device.port)
    finally:
        held.close()
    assert error.code == "PORT_OPEN_FAILED"
    assert device.port in error.message


def test_open_when_the_capture_process_cannot_start(root, device):
    error = fails(root, "serial_open", port=device.port, baud=10**30)
    assert error.code == "CAPTURE_FAILED"
    assert ".zquire/logs/serial.log" in error.hint
    assert (root / ".zquire" / "logs" / "serial.log").read_text()


def port(device, vid=None, description="n/a"):
    info = ListPortInfo(device, skip_link_detection=True)
    info.vid, info.description = vid, description
    return info


def test_open_detects_the_port(root, device, monkeypatch):
    candidates = [serial_port.Candidate(device.port, "pty")]
    monkeypatch.setattr(serial_port, "usb_ports", lambda: candidates)
    opened = call(root, "serial_open")
    assert (opened["port"], opened["detected"]) == (device.port, True)
    device.print("detected\n")
    captured(lambda tool, **a: call(root, tool, **a), 1)


def test_open_detects_no_port(root, monkeypatch):
    monkeypatch.setattr(serial_port, "usb_ports", list)
    assert fails(root, "serial_open").code == "PORT_NOT_FOUND"


def test_usb_candidates_need_a_vendor_id():
    ports = [port("/dev/ttyS0"), port("/dev/ttyACM0", 0x1366, "J-Link")]
    assert serial_port.usb_candidates(ports) == [serial_port.Candidate("/dev/ttyACM0", "J-Link")]


def test_pick_the_only_port():
    assert pick_port([serial_port.Candidate("/dev/ttyACM0", "J-Link")]) == "/dev/ttyACM0"


def test_pick_with_no_port():
    with pytest.raises(ZquireError) as raised:
        pick_port([])
    assert raised.value.code == "PORT_NOT_FOUND"
    assert raised.value.message and raised.value.hint


def test_pick_among_several_ports():
    candidates = [
        serial_port.Candidate("/dev/ttyACM0", "J-Link"),
        serial_port.Candidate("/dev/ttyUSB0", "CP2102"),
    ]
    with pytest.raises(ZquireError) as raised:
        pick_port(candidates)
    assert raised.value.code == "PORT_AMBIGUOUS"
    assert raised.value.hint
    assert "/dev/ttyACM0 (J-Link), /dev/ttyUSB0 (CP2102)" in raised.value.message


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("serial_read", {}),
        ("serial_wait", {"pattern": "x"}),
        ("serial_write", {"text": "x"}),
        ("serial_events", {}),
    ],
)
def test_tools_need_a_capture(root, tool, arguments):
    assert fails(root, tool, **arguments).code == "NO_CAPTURE"
    assert not (root / ".zquire").exists()


@pytest.mark.parametrize(
    ("tool", "arguments", "argument"),
    [
        ("serial_read", {"filter": "("}, "$.filter"),
        ("serial_wait", {"pattern": "[a"}, "$.pattern"),
    ],
)
def test_invalid_regex(capture, tool, arguments, argument):
    error = fails(capture, tool, **arguments)
    assert error.code == "INVALID_ARGUMENT"
    assert error.message.startswith(argument)


def test_read_arguments(capture, device):
    device.print("e1\nok\ne2\ne3\n")
    captured(lambda tool, **a: call(capture, tool, **a), 4)
    result = call(capture, "serial_read", cursor=1, limit=1, filter="^e")
    assert ([e["text"] for e in result["lines"]], result["next_cursor"]) == (["e2"], 3)


def test_wait_arguments(capture, device):
    device.print("ready 1\nready 2\nnot\n")
    captured(lambda tool, **a: call(capture, tool, **a), 3)
    assert call(capture, "serial_wait", pattern="ready", cursor=1)["line"]["text"] == "ready 2"
    started = time.monotonic()
    timed_out = call(capture, "serial_wait", pattern="nope", cursor=0, timeout_s=0, limit=2)
    assert time.monotonic() - started < 5
    assert ([e["text"] for e in timed_out["lines"]], timed_out["next_cursor"]) == (
        ["ready 1", "ready 2"],
        2,
    )


def test_wait_default_timeout_is_ten_seconds():
    assert serial.DEFAULT_WAIT_S == 10


def test_wait_default_timeout(capture, monkeypatch):
    monkeypatch.setattr(serial, "DEFAULT_WAIT_S", 0.3)
    started = time.monotonic()
    assert call(capture, "serial_wait", pattern="never")["status"] == "timeout"
    assert 0.3 <= time.monotonic() - started < 5


def test_wait_longer_than_the_request_timeout(capture, device, monkeypatch):
    monkeypatch.setattr(serial, "_REQUEST_TIMEOUT_S", 0.2)
    timer = threading.Timer(0.5, device.print, ["ready\n"])
    timer.start()
    result = call(capture, "serial_wait", pattern="ready", timeout_s=1)
    timer.join()
    assert result["status"] == "matched"


def test_close_during_a_wait(capture):
    closer = threading.Timer(0.3, call, [capture, "serial_close"])
    closer.start()
    assert call(capture, "serial_wait", pattern="x", timeout_s=10)["status"] == "closed"
    closer.join()


@pytest.fixture
def unresponsive(tmp_path, monkeypatch):
    """A workspace whose capture accepts requests but never answers them."""
    root = t2(tmp_path / "ws")
    monkeypatch.setattr(serial, "_REQUEST_TIMEOUT_S", 0.2)
    with socket_module.socket(socket_module.AF_UNIX) as listener:
        listener.bind(str(socket_path(locate(root))))
        listener.listen()
        yield root
    socket_path(locate(root)).unlink()


@pytest.mark.parametrize(
    ("tool", "arguments", "timeout"),
    [("serial_read", {}, 0.2), ("serial_wait", {"pattern": "x", "timeout_s": 0.3}, 0.5)],
)
def test_capture_that_does_not_answer(unresponsive, tool, arguments, timeout):
    started = time.monotonic()
    error = fails(unresponsive, tool, **arguments)
    assert timeout <= time.monotonic() - started < timeout + 2
    assert (error.code, error.message) == (
        "CAPTURE_FAILED",
        f"The serial capture did not answer within {timeout} s.",
    )


def test_write_line_ending(capture, device):
    assert call(capture, "serial_write", text="help", line_ending="\n")["sent"] == "help\n"
    assert device.received(6, timeout=0.3) == b"help\n"


def test_write_to_a_port_that_disappeared(capture, device):
    device.hang_up()
    captured(lambda tool, **a: call(capture, tool, **a), 1)
    assert call(capture, "serial_read")["lines"][0]["kind"] == "disconnected"
    error = fails(capture, "serial_write", text="help")
    assert (error.code, error.message) == (
        "CAPTURE_FAILED",
        f"The serial capture failed: {device.port} is disconnected",
    )
    assert call(capture, "serial_read", cursor=1)["lines"] == []


def test_events(capture, device):
    device.print("*** Booting Zephyr OS ***\nok\n>>> ZEPHYR FATAL ERROR 4: Kernel panic\n")
    captured(lambda tool, **a: call(capture, tool, **a), 3)
    found = call(capture, "serial_events")
    events = [(e["cursor"], e["event"]) for e in found["events"]]
    assert events == [(1, "boot"), (3, "kernel_panic")]
    assert (found["next_cursor"], found["truncated"]) == (3, False)
    assert call(capture, "serial_events", cursor=1, limit=1)["events"][0]["cursor"] == 3


def test_usb_ports_are_candidates():
    assert all(isinstance(c, serial_port.Candidate) for c in serial_port.usb_ports())


def test_close(root, device):
    call(root, "serial_open", port=device.port)
    started = time.monotonic()
    assert call(root, "serial_close") == {"closed": True}
    assert time.monotonic() - started < 1
    assert not socket_path(locate(root)).exists()
    assert call(root, "serial_close") == {"closed": False}
    assert fails(root, "serial_read").code == "NO_CAPTURE"


def test_close_releases_the_port_for_the_next_capture(root, device):
    call(root, "serial_open", port=device.port)
    call(root, "serial_close")
    assert call(root, "serial_open", port=device.port)["already_open"] is False


def test_close_without_a_capture_does_not_create_state(root):
    call(root, "serial_close")
    assert not (root / ".zquire").exists()


def test_capture_outlives_the_cli_that_opened_it(root, device):
    opened = subprocess.run(
        [sys.executable, "-c", "from zquire.cli import main; raise SystemExit(main())"]
        + ["--workspace", str(root), "serial_open", "--port", device.port],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
    )
    assert '"already_open": false' in opened.stdout
    device.print("still here\n")
    captured(lambda tool, **a: call(root, tool, **a), 1)


def test_captures_are_per_workspace(tmp_path, device):
    roots = [t2(tmp_path / "one"), t2(tmp_path / "two")]
    assert socket_path(locate(roots[0])) != socket_path(locate(roots[1]))
    other = Device()
    try:
        call(roots[0], "serial_open", port=device.port)
        call(roots[1], "serial_open", port=other.port)
        device.print("one\n")
        captured(lambda tool, **a: call(roots[0], tool, **a), 1)
        assert call(roots[1], "serial_read")["lines"] == []
    finally:
        for root in roots:
            call(root, "serial_close")
        other.close()


def test_socket_path_is_short(tmp_path):
    deep = t2(tmp_path / ("d" * 150))
    assert len(str(socket_path(locate(deep)))) < 100


def test_killed_capture_process(root, device):
    call(root, "serial_open", port=device.port)
    socket = socket_path(locate(root))
    os.kill(ipc.request(socket, {"op": "info"}, 5)["result"]["pid"], signal.SIGKILL)
    deadline = time.monotonic() + 5
    while True:
        try:
            ipc.request(socket, {"op": "info"}, 5)
        except ipc.Unreachable:
            break
        assert time.monotonic() < deadline
    assert socket.exists()
    assert fails(root, "serial_read").code == "NO_CAPTURE"
    assert call(root, "serial_open", port=device.port)["already_open"] is False
