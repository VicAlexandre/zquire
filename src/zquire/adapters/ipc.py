import json
import socket
import socketserver
from collections.abc import Callable
from pathlib import Path


class Unreachable(Exception):
    pass


def request(path: Path, message: dict, timeout: float) -> dict:
    """Send one JSON message over a Unix socket and return the JSON reply."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        try:
            connection.connect(str(path))
            connection.sendall(json.dumps(message).encode() + b"\n")
            with connection.makefile("rb") as replies:
                reply = replies.readline()
        # Refused or reset when the server is gone, as when it was killed.
        except (FileNotFoundError, ConnectionError) as error:
            raise Unreachable(str(error)) from error
    if not reply:
        raise Unreachable("the server closed the connection without replying")
    return json.loads(reply)


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    # Joined on server_close, so a reply being written is not cut off when the server exits.
    daemon_threads = False
    block_on_close = True


def server(path: Path, handle: Callable[[dict], dict]) -> socketserver.BaseServer:
    """A server answering each JSON line on a Unix socket with handle's JSON reply."""

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            message = self.rfile.readline()
            if message:
                self.wfile.write(json.dumps(handle(json.loads(message))).encode() + b"\n")

    return _Server(str(path), Handler)
