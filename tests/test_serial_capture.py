import json
import os
import re
import threading
import time

import pytest

from tests.serial_device import Device
from zquire.adapters import serial_port
from zquire.core import serial_capture
from zquire.core.serial_capture import Capture


@pytest.fixture
def capture(device):
    capture = Capture(device.port, 9600, serial_port.open_port(device.port, 9600), 100)
    pump = threading.Thread(target=capture.pump)
    pump.start()
    yield capture
    capture.handle({"op": "close"})
    pump.join(timeout=5)
    assert not pump.is_alive()


def until(condition, timeout=5):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def result(capture, **request):
    reply = capture.handle(request)
    assert reply["ok"], reply
    return reply["result"]


def test_pump_buffers_received_lines(capture, device):
    device.print(b"one\r\ntw")
    until(lambda: capture.buffer.last_cursor() == 1)
    device.print(b"o \xff\r\n")
    until(lambda: capture.buffer.last_cursor() == 2)
    lines = result(capture, op="read", cursor=0, limit=200, filter=None)["lines"]
    assert [(e["kind"], e["text"], e["invalid_utf8"]) for e in lines] == [
        ("rx", "one", False),
        ("rx", "two �", True),
    ]


def test_info(capture, device):
    device.print("a\n")
    until(lambda: capture.buffer.last_cursor() == 1)
    assert result(capture, op="info") == {
        "port": device.port,
        "baud": 9600,
        "buffer_lines": 100,
        "next_cursor": 1,
        "pid": os.getpid(),
    }


def test_read_with_filter_limit_and_cursor(capture, device):
    device.print("e1\nok\ne2\ne3\n")
    until(lambda: capture.buffer.last_cursor() == 4)
    read = result(capture, op="read", cursor=1, limit=1, filter="^e")
    assert ([e["text"] for e in read["lines"]], read["next_cursor"]) == (["e2"], 3)


def test_wait_defaults_to_the_end_of_the_buffer(capture, device):
    device.print("ready before\n")
    until(lambda: capture.buffer.last_cursor() == 1)
    timer = threading.Timer(0.1, device.print, ["ready after\n"])
    timer.start()
    waited = result(capture, op="wait", pattern="ready", cursor=None, timeout=5, limit=200)
    timer.join()
    assert waited["line"]["text"] == "ready after"


def test_wait_limit(capture, device):
    device.print("a\nb\n")
    until(lambda: capture.buffer.last_cursor() == 2)
    waited = result(capture, op="wait", pattern="z", cursor=0, timeout=0, limit=1)
    assert ([e["text"] for e in waited["lines"]], waited["next_cursor"]) == (["a"], 1)


def test_open_port_at_a_baud_rate(device):
    port = serial_port.open_port(device.port, 57600)
    try:
        assert (port.baudrate, port.timeout) == (57600, serial_port.READ_TIMEOUT_S)
    finally:
        port.close()


def test_wait_from_a_cursor(capture, device):
    device.print("ready before\n")
    until(lambda: capture.buffer.last_cursor() == 1)
    waited = result(capture, op="wait", pattern="ready", cursor=0, timeout=0, limit=200)
    assert waited["line"]["text"] == "ready before"


@pytest.mark.parametrize("ending", ["\r\n", "\n", ""])
def test_write(capture, device, ending):
    written = result(capture, op="write", text="kernel version", line_ending=ending)
    assert written == {"cursor": 1, "sent": "kernel version" + ending}
    expected = ("kernel version" + ending).encode()
    assert device.received(len(expected) + 1, timeout=0.3) == expected
    entry = capture.buffer.read(0, 200)["lines"][0]
    assert (entry["kind"], entry["text"]) == ("tx", "kernel version")


def test_close(capture):
    assert capture.handle({"op": "close"}) == {"ok": True, "result": {}}
    assert capture.closed.is_set()
    assert capture.buffer.wait(re.compile("x"), 0, 10, 1)["status"] == "closed"


def test_unknown_operation(capture):
    assert capture.handle({"op": "dance"}) == {"ok": False, "error": "unknown operation 'dance'"}


def test_main_reports_a_missing_port(tmp_path, capsys):
    arguments = ["--port", str(tmp_path / "nope"), "--baud", "1", "--socket", str(tmp_path / "s")]
    arguments += ["--buffer-lines", "10"]
    assert serial_capture.main(arguments) == 1
    reply = json.loads(capsys.readouterr().out)
    assert (reply["ok"], reply["missing"]) == (False, True)
    assert "nope" in reply["error"]
    assert not (tmp_path / "s").exists()


def test_main_reports_a_port_held_elsewhere(tmp_path, device, capsys):
    held = serial_port.open_port(device.port, 115200)
    try:
        arguments = ["--port", device.port, "--baud", "115200", "--socket", str(tmp_path / "s")]
        arguments += ["--buffer-lines", "10"]
        assert serial_capture.main(arguments) == 1
    finally:
        held.close()
    reply = json.loads(capsys.readouterr().out)
    assert (reply["ok"], reply["missing"]) == (False, False)


def entries(capture):
    return [(e["kind"], e["text"]) for e in capture.buffer.read(0, 200)["lines"]]


def kinds(capture):
    return [kind for kind, _ in entries(capture)]


@pytest.fixture
def linked(tmp_path, device):
    """A capture on a symlink to the device, which tests point at another device or remove,
    as a USB device's name comes and goes when it re-enumerates."""
    link = tmp_path / "console"
    link.symlink_to(device.port)
    capture = Capture(str(link), 9600, serial_port.open_port(str(link), 9600), 100)
    pump = threading.Thread(target=capture.pump)
    pump.start()
    yield capture, link
    capture.handle({"op": "close"})
    pump.join(timeout=5)
    assert not pump.is_alive()


def replug(link, device):
    link.unlink(missing_ok=True)
    link.symlink_to(device.port)


def test_release_closes_the_port_after_a_flash_marker(capture, device):
    device.print("before\npartial")
    until(lambda: capture.buffer.last_cursor() == 1)
    assert result(capture, op="release") == {}
    assert entries(capture) == [
        ("rx", "before"),
        ("rx", "partial"),
        ("flash", "Port released for flashing."),
    ]
    flasher = serial_port.open_port(device.port, 9600)
    flasher.close()
    reply = capture.handle({"op": "write", "text": "x", "line_ending": "\n"})
    assert reply == {"ok": False, "error": f"{device.port} is released for flashing"}


def test_resume_reopens_the_port(capture, device):
    result(capture, op="release")
    started = time.monotonic()
    assert result(capture, op="resume", timeout=5) == {"reopened": True}
    assert time.monotonic() - started < 0.3
    device.print("*** Booting Zephyr OS build v4.4.0 ***\n")
    until(lambda: capture.buffer.last_cursor() == 2)
    assert entries(capture)[-1] == ("rx", "*** Booting Zephyr OS build v4.4.0 ***")
    assert result(capture, op="write", text="x", line_ending="\n")["sent"] == "x\n"


def test_resume_waits_for_the_device_to_come_back(linked, device):
    capture, link = linked
    result(capture, op="release")
    device.close()
    link.unlink()
    again = Device()
    try:
        threading.Timer(0.5, replug, [link, again]).start()
        started = time.monotonic()
        assert result(capture, op="resume", timeout=5) == {"reopened": True}
        assert 0.5 <= time.monotonic() - started < 5
        again.print("new firmware\n")
        until(lambda: kinds(capture)[-1:] == ["rx"])
        assert entries(capture) == [
            ("flash", "Port released for flashing."),
            ("rx", "new firmware"),
        ]
    finally:
        result(capture, op="close")
        again.close()


def test_resume_gives_up_but_keeps_trying(linked, device):
    capture, link = linked
    result(capture, op="release")
    device.close()
    link.unlink()
    assert result(capture, op="resume", timeout=0.3) == {"reopened": False}
    assert entries(capture)[-1] == (
        "disconnected",
        f"{link} did not come back within 0.3 s of flashing.",
    )
    again = Device()
    try:
        replug(link, again)
        until(lambda: capture.handle({"op": "write", "text": "hi", "line_ending": "\n"})["ok"])
    finally:
        result(capture, op="close")
        again.close()


def test_resume_without_a_release(capture):
    assert result(capture, op="resume", timeout=0) == {"reopened": True}


def test_port_disappearing_and_coming_back(linked, device):
    capture, link = linked
    device.print("one\ntw")
    until(lambda: capture.buffer.last_cursor() == 1)
    device.close()
    link.unlink()
    until(lambda: kinds(capture)[-1:] == ["disconnected"])
    assert entries(capture)[:2] == [("rx", "one"), ("rx", "tw")]
    assert entries(capture)[2][1].startswith(f"{link} disappeared: ")
    reply = capture.handle({"op": "write", "text": "x", "line_ending": "\n"})
    assert reply == {"ok": False, "error": f"{link} is disconnected"}
    time.sleep(0.5)
    assert kinds(capture) == ["rx", "rx", "disconnected"]
    again = Device()
    try:
        replug(link, again)
        until(lambda: capture.handle({"op": "write", "text": "x", "line_ending": "\n"})["ok"])
        again.print("back\n")
        until(lambda: kinds(capture)[-1:] == ["rx"])
        assert entries(capture)[-2:] == [("tx", "x"), ("rx", "back")]
    finally:
        result(capture, op="close")
        again.close()


def test_release_while_disconnected_still_marks_the_flash(linked, device):
    capture, link = linked
    device.close()
    link.unlink()
    until(lambda: kinds(capture)[-1:] == ["disconnected"])
    result(capture, op="release")
    assert kinds(capture) == ["disconnected", "flash"]


def test_events(capture, device):
    device.print("x\n*** Booting Zephyr OS build v4.4.0 ***\ny\nASSERTION FAIL [a] @ b:1\n")
    until(lambda: capture.buffer.last_cursor() == 4)
    found = result(capture, op="events", cursor=0, limit=200)
    assert [(e["cursor"], e["event"]) for e in found["events"]] == [(2, "boot"), (4, "assertion")]
    assert (found["next_cursor"], found["truncated"]) == (4, False)
    assert "lines" not in found
    later = result(capture, op="events", cursor=2, limit=200)
    assert [e["cursor"] for e in later["events"]] == [4]
    first = result(capture, op="events", cursor=0, limit=1)
    assert ([e["cursor"] for e in first["events"]], first["next_cursor"]) == ([2], 2)


def test_buffer_capacity(device):
    capture = Capture(device.port, 9600, serial_port.open_port(device.port, 9600), 2)
    pump = threading.Thread(target=capture.pump)
    pump.start()
    try:
        device.print("a\nb\nc\n")
        until(lambda: capture.buffer.last_cursor() == 3)
        read = result(capture, op="read", cursor=0, limit=200, filter=None)
        assert ([e["text"] for e in read["lines"]], read["truncated"]) == (["b", "c"], True)
    finally:
        result(capture, op="close")
        pump.join(timeout=5)


def test_close_closes_the_port(capture, device):
    result(capture, op="close")
    until(lambda: capture._port is None)
    serial_port.open_port(device.port, 9600).close()


def test_a_long_release_marks_the_flash_once(capture):
    result(capture, op="release")
    time.sleep(0.3)
    assert kinds(capture) == ["flash"]
    result(capture, op="resume", timeout=5)


def test_write_that_fails(device):
    capture = Capture(device.port, 9600, serial_port.open_port(device.port, 9600), 10)
    device.hang_up()
    reply = capture.handle({"op": "write", "text": "x" * 4096, "line_ending": "\n"})
    assert reply["ok"] is False
    assert reply["error"].startswith(f"writing to {device.port} failed: ")
    assert capture.buffer.last_cursor() == 0
    capture._close_port()
