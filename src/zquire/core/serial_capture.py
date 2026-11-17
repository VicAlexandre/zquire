"""The capture process: owns the port, buffers its lines and answers the serial tools."""

import argparse
import json
import os
import re
import sys
import threading
from pathlib import Path

import serial

from zquire.adapters import ipc, serial_port
from zquire.core.serial_buffer import Buffer, Lines, decode

REOPEN_INTERVAL_S = 0.2
_RELEASE_TIMEOUT_S = 5


class Capture:
    def __init__(self, device: str, baud: int, port: serial.Serial, capacity: int) -> None:
        self.device = device
        self.baud = baud
        self.capacity = capacity
        self.buffer = Buffer(capacity)
        self.closed = threading.Event()
        self._port: serial.Serial | None = port
        # Held while the port is written to or swapped, so a write never meets a closed port.
        self._lock = threading.Lock()
        self._lines = Lines()
        self._released = False
        self._idle = threading.Event()
        self._connected = threading.Event()
        self._connected.set()

    def pump(self) -> None:
        """Move received lines into the buffer until the capture is closed."""
        while not self.closed.is_set():
            if self._released:
                if not self._idle.is_set():
                    self._close_port()
                    self.buffer.add("flash", "Port released for flashing.")
                    self._idle.set()
                self.closed.wait(REOPEN_INTERVAL_S / 4)
            elif self._port is None:
                if not self._reopen():
                    self.closed.wait(REOPEN_INTERVAL_S)
            else:
                try:
                    data = self._port.read(self._port.in_waiting or 1)
                except serial.SerialException as error:
                    self._close_port()
                    self.buffer.add("disconnected", f"{self.device} disappeared: {error}")
                    continue
                self._receive(self._lines.feed(data))
        self._close_port()

    def _receive(self, lines: list[bytes]) -> None:
        for raw in lines:
            self.buffer.add("rx", *decode(raw))

    def _close_port(self) -> None:
        self._receive(self._lines.flush())
        with self._lock:
            if self._port is not None:
                self._port.close()
            self._port = None
        self._connected.clear()

    def _reopen(self) -> bool:
        try:
            port = serial_port.open_port(self.device, self.baud)
        except serial_port.PortError:
            return False
        with self._lock:
            self._port = port
        self._connected.set()
        return True

    def _write(self, data: bytes) -> str | None:
        with self._lock:
            if self._port is None:
                state = "released for flashing" if self._released else "disconnected"
                return f"{self.device} is {state}"
            try:
                self._port.write(data)
                self._port.flush()
            except serial.SerialException as error:
                return f"writing to {self.device} failed: {error}"
        return None

    def handle(self, request: dict) -> dict:
        operation = request.get("op")
        if operation == "info":
            result = {
                "port": self.device,
                "baud": self.baud,
                "buffer_lines": self.capacity,
                "next_cursor": self.buffer.last_cursor(),
                "pid": os.getpid(),
            }
        elif operation == "read":
            pattern = request.get("filter")
            keep = None if pattern is None else re.compile(pattern)
            result = self.buffer.read(
                request["cursor"],
                request["limit"],
                None if keep is None else (lambda entry: bool(keep.search(entry["text"]))),
            )
        elif operation == "events":
            read = self.buffer.read(
                request["cursor"], request["limit"], lambda entry: entry["event"] is not None
            )
            result = {
                "events": read["lines"],
                "next_cursor": read["next_cursor"],
                "truncated": read["truncated"],
            }
        elif operation == "wait":
            cursor = request.get("cursor")
            result = self.buffer.wait(
                re.compile(request["pattern"]),
                self.buffer.last_cursor() if cursor is None else cursor,
                request["timeout"],
                request["limit"],
            )
        elif operation == "write":
            sent = request["text"] + request["line_ending"]
            failure = self._write(sent.encode())
            if failure is not None:
                return {"ok": False, "error": failure}
            result = {"cursor": self.buffer.add("tx", request["text"])["cursor"], "sent": sent}
        elif operation == "release":
            self._idle.clear()
            self._released = True
            self._idle.wait(_RELEASE_TIMEOUT_S)
            result = {}
        elif operation == "resume":
            self._released = False
            reopened = self._connected.wait(request["timeout"])
            if not reopened:
                self.buffer.add(
                    "disconnected",
                    f"{self.device} did not come back within {request['timeout']} s of flashing.",
                )
            result = {"reopened": reopened}
        elif operation == "close":
            self.buffer.close()
            self.closed.set()
            result = {}
        else:
            return {"ok": False, "error": f"unknown operation {operation!r}"}
        return {"ok": True, "result": result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zquire-serial-capture")
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--buffer-lines", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        port = serial_port.open_port(args.port, args.baud)
    except serial_port.PortError as error:
        print(json.dumps({"ok": False, "missing": error.missing, "error": str(error)}))
        return 1
    capture = Capture(args.port, args.baud, port, args.buffer_lines)
    server = ipc.server(args.socket, capture.handle)
    print(json.dumps({"ok": True, "pid": os.getpid()}), flush=True)
    # The process that started this one stops reading after the first line.
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    pump = threading.Thread(target=capture.pump)
    pump.start()
    capture.closed.wait()
    server.shutdown()
    server.server_close()
    pump.join()
    args.socket.unlink(missing_ok=True)
    return 0


def run() -> None:
    """The capture process's entry point."""
    # Forked off and in a session of its own, the capture outlives whatever started it, as a
    # CLI command does, and is never left for that process to reap.
    if os.fork():
        os._exit(0)
    os.setsid()
    sys.exit(main())
