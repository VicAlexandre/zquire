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


class Capture:
    def __init__(self, port: serial.Serial, baud: int) -> None:
        self.port = port
        self.baud = baud
        self.buffer = Buffer()
        self.closed = threading.Event()
        self._lines = Lines()

    def pump(self) -> None:
        """Move received lines into the buffer until the capture is closed."""
        while not self.closed.is_set():
            try:
                data = self.port.read(self.port.in_waiting or 1)
            except serial.SerialException as error:
                print(f"Capture on {self.port.port} stopped: {error}", file=sys.stderr)
                return
            for raw in self._lines.feed(data):
                self.buffer.add("rx", *decode(raw))

    def handle(self, request: dict) -> dict:
        operation = request.get("op")
        if operation == "info":
            result = {
                "port": self.port.port,
                "baud": self.baud,
                "next_cursor": self.buffer.last_cursor(),
                "pid": os.getpid(),
            }
        elif operation == "read":
            pattern = request.get("filter")
            result = self.buffer.read(
                request["cursor"],
                request["limit"],
                None if pattern is None else re.compile(pattern),
            )
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
            try:
                self.port.write(sent.encode())
                self.port.flush()
            except serial.SerialException as error:
                return {"ok": False, "error": f"writing to {self.port.port} failed: {error}"}
            result = {"cursor": self.buffer.add("tx", request["text"])["cursor"], "sent": sent}
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
    args = parser.parse_args(argv)
    try:
        port = serial_port.open_port(args.port, args.baud)
    except serial_port.PortError as error:
        print(json.dumps({"ok": False, "missing": error.missing, "error": str(error)}))
        return 1
    capture = Capture(port, args.baud)
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
    port.close()
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
