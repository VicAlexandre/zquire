import socket
import threading

import pytest

from zquire.adapters import ipc


@pytest.fixture
def path(tmp_path):
    return tmp_path / "s"


def serving(server):
    thread = threading.Thread(target=server.serve_forever, args=(0.01,))
    thread.start()
    return thread


def test_request_and_reply(path):
    server = ipc.server(path, lambda message: {"echo": message, "ok": True})
    thread = serving(server)
    try:
        assert ipc.request(path, {"op": "x", "n": [1]}, 5) == {
            "echo": {"op": "x", "n": [1]},
            "ok": True,
        }
        assert ipc.request(path, {"op": "y"}, 5)["echo"] == {"op": "y"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_connection_closed_without_a_message_is_ignored(path):
    handled = []
    server = ipc.server(path, lambda message: handled.append(message) or {})
    thread = serving(server)
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.connect(str(path))
        # Served after the empty connection, as connections are accepted in order.
        ipc.request(path, {"op": "after"}, 5)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert handled == [{"op": "after"}]


def test_no_server(path):
    with pytest.raises(ipc.Unreachable):
        ipc.request(path, {}, 5)


def test_socket_left_by_a_dead_server(path):
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
    with pytest.raises(ipc.Unreachable):
        ipc.request(path, {}, 5)


def test_server_that_closes_without_replying(path):
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
        listener.listen()

        def accept_and_close():
            connection, _ = listener.accept()
            connection.recv(100)
            connection.close()

        thread = threading.Thread(target=accept_and_close)
        thread.start()
        with pytest.raises(ipc.Unreachable, match="without replying"):
            ipc.request(path, {}, 5)
        thread.join()
