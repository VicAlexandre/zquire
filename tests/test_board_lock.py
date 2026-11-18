import subprocess
import sys
import threading
import time

import pytest

from tests.workspaces import fake_west_build, flash_calls, flash_port, t2, t3, twister_calls
from zquire.core import board_lock
from zquire.core.context import Context
from zquire.core.workspace import locate
from zquire.errors import ZquireError
from zquire.tools import TOOLS, invoke


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(board_lock, "LOCK_TIMEOUT_S", 0.3)
    root = fake_west_build(t3(tmp_path / "ws", "app"))
    (root / "app" / "src").mkdir()
    (root / "app" / "src" / "main.c").write_text("int main(void) { return 0; }\n")
    return root


def call(root, tool, **arguments):
    return invoke(TOOLS[tool], arguments, Context(locate(root)))


def busy(root, tool, **arguments):
    with pytest.raises(ZquireError) as error:
        call(root, tool, **arguments)
    return error.value


def test_a_free_board_is_held_at_once(root):
    started = time.monotonic()
    with board_lock.hold(locate(root), "flash"):
        assert time.monotonic() - started < 0.1


def test_waits_for_the_holder_to_finish(root):
    workspace = locate(root)
    held = threading.Event()

    def holder():
        with board_lock.hold(workspace, "flash"):
            held.set()
            time.sleep(0.2)

    thread = threading.Thread(target=holder)
    thread.start()
    held.wait()
    started = time.monotonic()
    with board_lock.hold(workspace, "runtime_stats"):
        assert 0.1 < time.monotonic() - started < 0.3
    thread.join()


def test_busy_names_the_holder(root):
    workspace = locate(root)
    with board_lock.hold(workspace, "flash"):
        started = time.monotonic()
        with pytest.raises(ZquireError) as error, board_lock.hold(workspace, "runtime_stats"):
            pass
        assert 0.3 <= time.monotonic() - started < 1
    assert error.value.code == "BUSY"
    assert error.value.message == (
        "The board is in use by flash, which did not finish within 0.3 s."
    )
    assert error.value.hint == "Call again once it has finished."


def test_released_when_the_operation_fails(root):
    workspace = locate(root)
    with pytest.raises(RuntimeError), board_lock.hold(workspace, "flash"):
        raise RuntimeError("west is gone")
    with board_lock.hold(workspace, "flash"):
        pass


def test_held_across_processes_and_released_when_the_holder_dies(root):
    path = locate(root).runtime_path(".lock")
    script = (
        "import fcntl, sys, time\n"
        f"handle = open({str(path)!r}, 'a+')\n"
        "fcntl.flock(handle, fcntl.LOCK_EX)\n"
        "handle.truncate(0); handle.write('twister'); handle.flush()\n"
        "print('held', flush=True)\n"
        "time.sleep(60)\n"
    )
    other = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    try:
        assert other.stdout.readline() == "held\n"
        with pytest.raises(ZquireError) as error, board_lock.hold(locate(root), "flash"):
            pass
        assert "in use by twister" in error.value.message
    finally:
        other.kill()
        other.wait()
    with board_lock.hold(locate(root), "flash"):
        pass


def test_each_workspace_has_its_own_board(root, tmp_path):
    other = t2(tmp_path / "other")
    with board_lock.hold(locate(root), "flash"), board_lock.hold(locate(other), "flash"):
        pass


def test_flash_waits_for_the_board(root):
    call(root, "build", application="app", board="b")
    with board_lock.hold(locate(root), "runtime_stats"):
        assert busy(root, "flash").code == "BUSY"
    assert flash_calls(root) == []
    assert call(root, "flash")["status"] == "success"


def test_refused_flash_does_not_wait_for_the_board(root):
    with board_lock.hold(locate(root), "runtime_stats"):
        started = time.monotonic()
        assert busy(root, "flash").code == "NO_BUILD"
        assert time.monotonic() - started < 0.3


def test_device_testing_waits_for_the_board(root):
    arguments = {"paths": ["app"], "platform": "b", "device_testing": True}
    with board_lock.hold(locate(root), "flash"):
        error = busy(root, "twister", device_serial="/dev/ttyACM0", **arguments)
    assert error.code == "BUSY"
    assert twister_calls(root) == []


def test_device_testing_keeps_the_last_run_while_waiting(root):
    call(root, "twister", paths=["app"], platform="b")
    arguments = {"paths": ["app"], "platform": "b", "device_testing": True}
    with board_lock.hold(locate(root), "flash"):
        busy(root, "twister", device_serial="/dev/ttyACM0", **arguments)
    assert (root / ".zquire" / "twister" / "twister.json").is_file()


def test_emulated_twister_does_not_wait_for_the_board(root):
    with board_lock.hold(locate(root), "flash"):
        assert call(root, "twister", paths=["app"], platform="native_sim")["status"] == "success"


def test_serial_open_waits_for_the_board(root, device):
    with board_lock.hold(locate(root), "flash"):
        assert busy(root, "serial_open", port=device.port).code == "BUSY"
    assert call(root, "serial_close") == {"closed": False}


def test_serial_close_waits_for_the_board(root, device):
    call(root, "serial_open", port=device.port)
    try:
        with board_lock.hold(locate(root), "flash"):
            assert busy(root, "serial_close").code == "BUSY"
        assert call(root, "serial_read")["lines"] == []
    finally:
        assert call(root, "serial_close") == {"closed": True}


def test_busy_names_a_running_flash(root, tmp_path, device):
    call(root, "build", application="app", board="b")
    console = tmp_path / "console"
    console.symlink_to(device.port)
    # The fake flash re-enumerates the console, and takes a second to bring it back.
    flash_port(root, console, device.port, delay=1)
    flashing = threading.Thread(target=call, args=(root, "flash"))
    flashing.start()
    try:
        while console.exists():
            time.sleep(0.01)
        error = busy(root, "serial_close")
        assert (error.code, error.message.split(",")[0]) == ("BUSY", "The board is in use by flash")
    finally:
        flashing.join()
