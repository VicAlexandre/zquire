import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import zquire
from zquire.adapters import ipc, serial_port
from zquire.adapters.store import prepare_state_dir
from zquire.core.context import Context
from zquire.core.serial_buffer import DEFAULT_CAPACITY
from zquire.core.workspace import Workspace
from zquire.errors import ZquireError

DEFAULT_BAUD = 115200
DEFAULT_LIMIT = 200
DEFAULT_WAIT_S = 10
# How long a device may take to come back after flashing, as USB consoles re-enumerate.
RESUME_TIMEOUT_S = 10
_REQUEST_TIMEOUT_S = 10
_CLOSE_TIMEOUT_S = 5


def socket_path(workspace: Workspace) -> Path:
    # In the temporary directory, as Unix socket paths are limited to about 100 bytes.
    digest = hashlib.sha256(str(workspace.root).encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"zquire-{digest}.sock"


def _no_capture() -> ZquireError:
    return ZquireError("NO_CAPTURE", "No serial capture is open.", "Call serial_open first.")


def _reply(workspace: Workspace, message: dict, waiting_s: float = 0) -> dict | None:
    """The capture process's reply, or None when no capture is open."""
    timeout = waiting_s + _REQUEST_TIMEOUT_S
    try:
        return ipc.request(socket_path(workspace), message, timeout)
    except ipc.Unreachable:
        return None
    except TimeoutError as error:
        raise ZquireError(
            "CAPTURE_FAILED",
            f"The serial capture did not answer within {timeout} s.",
            "Call serial_close, then serial_open again.",
        ) from error


def _request(workspace: Workspace, message: dict, waiting_s: float = 0) -> dict:
    reply = _reply(workspace, message, waiting_s)
    if reply is None:
        raise _no_capture()
    if not reply["ok"]:
        raise ZquireError(
            "CAPTURE_FAILED",
            f"The serial capture failed: {reply['error']}",
            "Call serial_close, then serial_open again.",
        )
    return reply["result"]


def _compile(pattern: str, argument: str) -> str:
    try:
        re.compile(pattern)
    except re.error as error:
        raise ZquireError(
            "INVALID_ARGUMENT",
            f"$.{argument}: {pattern!r} is not a valid regular expression: {error}",
            "Use Python regular expression syntax, escaping special characters with '\\'.",
        ) from error
    return pattern


def pick_port(candidates: list[serial_port.Candidate]) -> str:
    if not candidates:
        raise ZquireError(
            "PORT_NOT_FOUND",
            "No USB serial port was found to detect the board's console on.",
            "Connect the board, or pass port.",
        )
    if len(candidates) > 1:
        listed = ", ".join(f"{c.device} ({c.description})" for c in candidates)
        raise ZquireError(
            "PORT_AMBIGUOUS",
            f"Several USB serial ports were found: {listed}.",
            "Pass port to choose one.",
        )
    return candidates[0].device


def _start(workspace: Workspace, device: str, baud: int, buffer_lines: int) -> None:
    socket = socket_path(workspace)
    # Left behind by a capture process that was killed.
    socket.unlink(missing_ok=True)
    log = prepare_state_dir(workspace.root) / "logs" / "serial.log"
    log.parent.mkdir(exist_ok=True)
    # The capture process must import this same zquire, wherever it was loaded from.
    search_path = [str(Path(zquire.__file__).parent.parent), os.environ.get("PYTHONPATH", "")]
    with log.open("a") as errors:
        process = subprocess.Popen(
            [sys.executable, "-c", "from zquire.core.serial_capture import run; run()"]
            + ["--port", device, "--baud", str(baud), "--socket", str(socket)]
            + ["--buffer-lines", str(buffer_lines)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=errors,
            env={**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, search_path))},
        )
    with process.stdout:
        started = process.stdout.readline()
    # Only the process that forked the capture off, which exits at once.
    process.wait()
    if not started:
        raise ZquireError(
            "CAPTURE_FAILED",
            "The serial capture process exited without opening the port.",
            f"See {workspace.relative(log)}.",
        )
    reply = json.loads(started)
    if reply["ok"]:
        return
    if reply["missing"]:
        raise ZquireError(
            "PORT_NOT_FOUND",
            f"Serial port {device} does not exist.",
            "Check the board is connected, or omit port to detect it.",
        )
    raise ZquireError(
        "PORT_OPEN_FAILED",
        f"Serial port {device} could not be opened: {reply['error']}",
        "Check that no other program, such as a terminal, holds the port, "
        "and that you may access it.",
    )


def serial_open(
    context: Context,
    port: str | None = None,
    baud: int | None = None,
    buffer_lines: int | None = None,
) -> dict:
    workspace = context.workspace
    reply = _reply(workspace, {"op": "info"})
    if reply is not None:
        info = reply["result"]
        other_port = port is not None and os.path.realpath(port) != os.path.realpath(info["port"])
        other_baud = baud is not None and baud != info["baud"]
        other_size = buffer_lines is not None and buffer_lines != info["buffer_lines"]
        if other_port or other_baud or other_size:
            raise ZquireError(
                "CAPTURE_OPEN",
                f"A serial capture is already open on {info['port']} at {info['baud']} baud, "
                f"holding {info['buffer_lines']} lines.",
                "Call serial_close first to change its port, baud rate or buffer size.",
            )
        opened = {
            "port": info["port"],
            "baud": info["baud"],
            "buffer_lines": info["buffer_lines"],
            "detected": False,
        }
        return {**opened, "already_open": True, "next_cursor": info["next_cursor"]}
    detected = port is None
    device = pick_port(serial_port.usb_ports()) if detected else port
    baud = DEFAULT_BAUD if baud is None else baud
    buffer_lines = DEFAULT_CAPACITY if buffer_lines is None else buffer_lines
    _start(workspace, device, baud, buffer_lines)
    return {
        "port": device,
        "baud": baud,
        "buffer_lines": buffer_lines,
        "detected": detected,
        "already_open": False,
        "next_cursor": 0,
    }


def serial_read(
    context: Context, cursor: int = 0, limit: int = DEFAULT_LIMIT, filter: str | None = None
) -> dict:
    message = {"op": "read", "cursor": cursor, "limit": limit, "filter": filter}
    if filter is not None:
        _compile(filter, "filter")
    return _request(context.workspace, message)


def serial_wait(
    context: Context,
    pattern: str,
    timeout_s: float | None = None,
    cursor: int | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    timeout_s = DEFAULT_WAIT_S if timeout_s is None else timeout_s
    message = {
        "op": "wait",
        "pattern": _compile(pattern, "pattern"),
        "timeout": timeout_s,
        "cursor": cursor,
        "limit": limit,
    }
    return _request(context.workspace, message, timeout_s)


def serial_events(context: Context, cursor: int = 0, limit: int = DEFAULT_LIMIT) -> dict:
    return _request(context.workspace, {"op": "events", "cursor": cursor, "limit": limit})


def serial_write(context: Context, text: str, line_ending: str = "\r\n") -> dict:
    return _request(context.workspace, {"op": "write", "text": text, "line_ending": line_ending})


def serial_close(context: Context) -> dict:
    workspace = context.workspace
    if _reply(workspace, {"op": "close"}) is None:
        return {"closed": False}
    # The process removes its socket last, once the port is released for the next capture.
    deadline = time.monotonic() + _CLOSE_TIMEOUT_S
    while socket_path(workspace).exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    return {"closed": True}


def capture_port(workspace: Workspace) -> str | None:
    reply = _reply(workspace, {"op": "info"})
    return reply["result"]["port"] if reply is not None else None


def release(workspace: Workspace) -> bool:
    return _reply(workspace, {"op": "release"}) is not None


def resume(workspace: Workspace) -> bool:
    reply = _reply(workspace, {"op": "resume", "timeout": RESUME_TIMEOUT_S}, RESUME_TIMEOUT_S)
    # A capture closed during the flash has no port to reopen.
    return reply is None or reply["result"]["reopened"]
