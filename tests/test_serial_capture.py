import json
import os
import re
import threading
import time

import pytest

from zquire.adapters import serial_port
from zquire.core import serial_capture
from zquire.core.serial_capture import Capture


@pytest.fixture
def capture(device):
    capture = Capture(serial_port.open_port(device.port, 9600), 9600)
    pump = threading.Thread(target=capture.pump)
    pump.start()
    yield capture
    capture.handle({"op": "close"})
    pump.join(timeout=5)
    assert not pump.is_alive()
    capture.port.close()


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


def test_port_failure_stops_the_pump(device, capsys):
    capture = Capture(serial_port.open_port(device.port, 9600), 9600)
    pump = threading.Thread(target=capture.pump)
    pump.start()
    device.hang_up()
    pump.join(timeout=5)
    assert not pump.is_alive()
    assert f"Capture on {device.port} stopped: " in capsys.readouterr().err
    reply = capture.handle({"op": "write", "text": "help", "line_ending": "\n"})
    assert reply["ok"] is False
    assert reply["error"].startswith(f"writing to {device.port} failed: ")
    assert capture.buffer.last_cursor() == 0
    capture.port.close()


def test_unknown_operation(capture):
    assert capture.handle({"op": "dance"}) == {"ok": False, "error": "unknown operation 'dance'"}


def test_main_reports_a_missing_port(tmp_path, capsys):
    arguments = ["--port", str(tmp_path / "nope"), "--baud", "1", "--socket", str(tmp_path / "s")]
    assert serial_capture.main(arguments) == 1
    reply = json.loads(capsys.readouterr().out)
    assert (reply["ok"], reply["missing"]) == (False, True)
    assert "nope" in reply["error"]
    assert not (tmp_path / "s").exists()


def test_main_reports_a_port_held_elsewhere(tmp_path, device, capsys):
    held = serial_port.open_port(device.port, 115200)
    try:
        arguments = ["--port", device.port, "--baud", "115200", "--socket", str(tmp_path / "s")]
        assert serial_capture.main(arguments) == 1
    finally:
        held.close()
    reply = json.loads(capsys.readouterr().out)
    assert (reply["ok"], reply["missing"]) == (False, False)
