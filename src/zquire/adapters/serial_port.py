import errno
from dataclasses import dataclass

import serial
from serial.tools import list_ports

READ_TIMEOUT_S = 0.1


class PortError(Exception):
    def __init__(self, missing: bool, message: str) -> None:
        super().__init__(message)
        self.missing = missing


@dataclass(frozen=True)
class Candidate:
    device: str
    description: str


def open_port(device: str, baud: int) -> serial.Serial:
    try:
        # Exclusive, so a second capture or a terminal cannot share the port unnoticed.
        return serial.Serial(device, baud, timeout=READ_TIMEOUT_S, exclusive=True)
    except serial.SerialException as error:
        missing = getattr(error, "errno", None) == errno.ENOENT
        raise PortError(missing, str(error)) from error


def usb_ports() -> list[Candidate]:
    return usb_candidates(list_ports.comports())


def usb_candidates(ports: list) -> list[Candidate]:
    """The ports with a USB vendor ID, where a board's console shows up."""
    return [Candidate(port.device, port.description) for port in ports if port.vid is not None]
