import os
import select
import time


class Device:
    """The far end of a pseudo-terminal, standing in for a board on a serial port."""

    def __init__(self) -> None:
        self._controller, self._port = os.openpty()
        self.port = os.ttyname(self._port)

    def print(self, data: bytes | str) -> None:
        os.write(self._controller, data.encode() if isinstance(data, str) else data)

    def received(self, size: int, timeout: float = 5) -> bytes:
        """What zquire sent, once size bytes have arrived or timeout seconds have passed."""
        data = b""
        deadline = time.monotonic() + timeout
        while (
            len(data) < size
            and select.select([self._controller], [], [], deadline - time.monotonic())[0]
        ):
            data += os.read(self._controller, size - len(data))
        return data

    def hang_up(self) -> None:
        """Close the device's end, so the port fails as when a board is unplugged."""
        if self._controller is not None:
            os.close(self._controller)
            self._controller = None

    def close(self) -> None:
        self.hang_up()
        os.close(self._port)


def captured(call, count: int, timeout: float = 5) -> None:
    """Wait until the capture holds count entries."""
    deadline = time.monotonic() + timeout
    while not call("serial_read", cursor=count - 1, limit=1)["lines"]:
        assert time.monotonic() < deadline, f"fewer than {count} entries were captured"
        time.sleep(0.01)
