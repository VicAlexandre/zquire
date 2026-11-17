# 7. Serial capture runs in its own process, reached over a Unix socket

## Context

SER-01 asks `serial_open` to start capturing a port into a buffer, which `serial_read`, `serial_wait` and `serial_write` then use (SER-03–06). The capture has to keep reading between tool calls. NFR-01 requires each tool as an MCP tool and as an equivalent CLI command, and every CLI command is a process that exits once it prints its result. Later requirements make the capture let go of its port and take it back: around a flash (SER-07, FLS-05), when the board is unplugged (SER-08), and during device testing (TWS-06). SER-12 rules out runtime dependencies that are not Python.

## Decision

- `serial_open` starts a capture process, `python -m zquire.core.serial_capture`, in a new session so it outlives whatever started it. It opens the port with pyserial (exclusively), reports success or the open error on its stdout, then keeps reading lines into an in-memory buffer until `serial_close`. Its stderr goes to `.zquire/logs/serial.log`.
- There is at most one capture per workspace. The serial tools reach it through a Unix socket named after a hash of the workspace root, in the system's temporary directory, as socket paths are limited to about 100 bytes. Each request and reply is one line of JSON. If nothing answers on the socket, there is no capture (`NO_CAPTURE`), and a socket left behind by a killed process is replaced.
- Cursors number the buffer's entries from 1. Received lines and sent text (`tx`) are entries alike. A read returns entries after a cursor. A wait matches only received lines and, by default, only those after the end of the buffer when it was called.
- `serial_open` with no port picks the only USB serial port (one with a USB vendor ID), and fails with `PORT_AMBIGUOUS` when there are several. Calling it again while a capture is open returns that capture, unless the port or baud rate differs (`CAPTURE_OPEN`).

## Alternatives

- **A thread in the MCP server** would work over MCP but not from the CLI, which would break NFR-01. It would also lose the capture whenever the server restarts.
- **Writing captured lines to a file in `.zquire/`** would let reads skip the socket, but writes, waits and releasing the port would still need to reach a process. A file would also have to be trimmed to keep it bounded (SER-09).
- **A localhost TCP port** is reachable by every user on the machine. Linux and macOS (NFR-07) both have Unix sockets.

## Consequences

A capture keeps running after the agent or the MCP server exits, until `serial_close` is called or the process is killed. The buffer is lost with the process. Flash, Twister and later tools can ask the capture to release and reopen its port over the same socket. A wait holds its tool call, and over MCP the server, until it matches or times out, as long builds and flashes already do. Coverage does not measure the capture process's `main`, though every tool test runs it.
