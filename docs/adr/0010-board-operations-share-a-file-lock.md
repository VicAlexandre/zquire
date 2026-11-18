# 10. Board operations share one file lock per workspace

## Context

NFR-04 asks zquire to serialise operations that use the same board: flash, ZView, device-testing Twister, and opening and closing a serial capture. A call that cannot get the board within 30 s fails with `BUSY`. FLS-07 applies this to flashing during a ZView dump. These operations can come from different processes: the MCP server, CLI commands, and more than one agent on the same workspace. zquire cannot tell which physical board a profile, port or probe reaches, and a serial capture has no profile at all.

## Decision

- Each workspace has one board, held through an exclusive `flock` on `zquire-<hash>.lock` in the temporary directory, named like the serial capture's socket. Every zquire process sees the same lock, and the system releases it when its holder exits, even when the holder is killed.
- A waiting call polls every 50 ms, and fails with `BUSY` after 30 s, naming the operation that holds the board. The holder writes its operation's name into the lock file.
- `flash` holds the board while west runs, after its checks pass, so a refused flash never waits. Twister holds it only for device testing. `serial_open` and `serial_close` hold it while they start or stop the capture. The capture itself does not hold it while it runs. It gives up its port on request instead (ADR 0008).

## Alternatives

- **A lock per board name or per port** would let two boards on one workspace work at once. zquire cannot tell whether two profiles reach one board or two, and the serial tools know only a port.
- **A lock inside the MCP server** would not reach CLI commands or a second server.
- **Waiting without a limit** would hang an agent behind a 30-minute Twister run.

## Consequences

Two boards attached to one workspace still take turns. Twister on an emulated platform runs alongside board operations, and two Twister runs at once still share one output directory.
